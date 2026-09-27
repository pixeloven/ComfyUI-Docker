"""The workflow tools and the run producer, against a fake ComfyUI that keeps a queue and a history the way
ComfyUI does. The real-ComfyUI counterpart is test_relay_workflow_live.py."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import comfyrelay.tools_workflow as tw
import httpx2
import pytest
from comfyrelay.comfyui import ComfyUIClient
from comfyrelay.server import build_server
from mcp import Client
from relay_helpers import SYSTEM_STATS, assert_producer_honours_cancel, settings

pytestmark = pytest.mark.anyio

INFO = json.loads((Path(__file__).parent / "object_info_v0.37.0.json").read_text())
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def t1() -> dict:
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": "harness-input.png"}},
        "2": {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["1", 0],
                "upscale_method": "nearest-exact",
                "width": 256,
                "height": 256,
                "crop": "disabled",
            },
        },
        "3": {"class_type": "ImageInvert", "inputs": {"image": ["2", 0]}},
        "4": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "t1_"}},
    }


SAVED = {"4": {"images": [{"filename": "t1__00001_.png", "subfolder": "", "type": "output"}]}}


class FakeComfyUI:
    """Just enough of ComfyUI's HTTP API: /object_info, /prompt, /queue, /history, /interrupt, /upload/image, /view.

    `auto` decides what happens to a submitted prompt: "success" finishes it at the next /queue poll, "error"
    fails it at node 2, "hold" leaves it queued until the test calls start() or finish()."""

    def __init__(self, auto: str = "success") -> None:
        self.auto = auto
        self.running: list[list] = []
        self.pending: list[list] = []
        self.history: dict[str, dict] = {}
        self.calls: list[tuple[str, str, object]] = []
        self.number = 0
        self.reject: dict | None = None
        self.accepted_node_errors: dict = {}
        self.files = {"t1__00001_.png": PNG}
        self.stored: dict[str, bytes] = {}
        self.slow: set[str] = set()  # paths that never answer
        self.down = False  # nothing answers at all

    def client(self) -> ComfyUIClient:
        return ComfyUIClient("http://comfyui.test:8188", transport=httpx2.MockTransport(self.handle))

    def posted(self, path: str) -> list:
        return [body for method, p, body in self.calls if method == "POST" and p == path]

    def start(self, prompt_id: str) -> None:
        item = next(i for i in self.pending if i[1] == prompt_id)
        self.pending.remove(item)
        self.running.append(item)

    def finish(self, prompt_id: str, status: str = "success", messages: list | None = None, outputs=None) -> None:
        for queue in (self.running, self.pending):
            queue[:] = [i for i in queue if i[1] != prompt_id]
        self.history[prompt_id] = {
            "outputs": SAVED if outputs is None else outputs,
            "status": {"status_str": status, "completed": status == "success", "messages": messages or []},
        }

    async def handle(self, request: httpx2.Request) -> httpx2.Response:
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.headers.get("content-type") == "application/json" else None
        if self.down:
            raise httpx2.ConnectError("refused", request=request)
        self.calls.append((method, path, body))
        if path in self.slow:
            await asyncio.sleep(30)
        if path == "/system_stats":
            return httpx2.Response(200, json=SYSTEM_STATS)
        if path == "/object_info":
            return httpx2.Response(200, json=INFO)
        if (method, path) == ("POST", "/prompt"):
            if self.reject is not None:
                return httpx2.Response(400, json=self.reject)
            self.number += 1
            self.pending.append([self.number, body["prompt_id"], body["prompt"], {}, []])
            return httpx2.Response(
                200,
                json={"prompt_id": body["prompt_id"], "number": self.number, "node_errors": self.accepted_node_errors},
            )
        if (method, path) == ("GET", "/queue"):
            for item in list(self.pending):
                if self.auto == "success":
                    self.finish(item[1])
                elif self.auto == "error":
                    self.finish(item[1], "error", [["execution_error", RUNTIME_ERROR]], outputs={})
            return httpx2.Response(200, json={"queue_running": self.running, "queue_pending": self.pending})
        if (method, path) == ("POST", "/queue"):
            for prompt_id in body.get("delete", []):
                self.pending[:] = [i for i in self.pending if i[1] != prompt_id]
            return httpx2.Response(200)
        if (method, path) == ("POST", "/interrupt"):
            for item in self.running:
                if item[1] == body.get("prompt_id"):
                    self.finish(item[1], "error", [["execution_interrupted", {"node_id": "3", "node_type": "X"}]])
            return httpx2.Response(200)
        if method == "GET" and path.startswith("/history/"):
            prompt_id = path.removeprefix("/history/")
            return httpx2.Response(200, json={prompt_id: self.history[prompt_id]} if prompt_id in self.history else {})
        if path == "/view":
            data = self.files.get(request.url.params.get("filename"))
            if data is None:
                return httpx2.Response(404)
            headers = {"content-type": "image/png", "content-length": str(len(data))}
            return httpx2.Response(200, headers=headers, content=b"" if method == "HEAD" else data)
        if (method, path) == ("POST", "/upload/image"):
            text = request.content
            name = text.split(b'filename="', 1)[1].split(b'"', 1)[0].decode()
            assert b'name="type"\r\n\r\ninput' in text and b'name="overwrite"\r\n\r\nfalse' in text
            stored = name
            if name in self.stored and self.stored[name] != text:  # ComfyUI keeps identical bytes, renames others
                stem, dot, ext = name.rpartition(".")
                stored = f"{stem} (1){dot}{ext}"
            self.stored[stored] = text
            return httpx2.Response(200, json={"name": stored, "subfolder": "", "type": "input"})
        return httpx2.Response(404)


LOADIMAGE_REJECTED = {
    "errors": [
        {
            "type": "custom_validation_failed",
            "message": "Custom validation failed for node",
            "details": "image - Invalid image file: harness-input.png",
            "extra_info": {"input_name": "image"},
        }
    ],
    "dependent_outputs": ["4"],
    "class_type": "LoadImage",
}

RUNTIME_ERROR = {
    "node_id": "2",
    "node_type": "ImageToMask",
    "exception_type": "IndexError",
    "exception_message": "index 3 is out of bounds for dimension 3 with size 3\n",
    "traceback": ["  File a\n", "  File b\n", "  File c\n"],
    "current_inputs": {"image": ["tensor(...)"]},
}


@pytest.fixture(autouse=True)
def fast_polls(monkeypatch):
    monkeypatch.setattr(tw, "POLL_SECONDS", 0.01)


def serve(fake: FakeComfyUI):
    return build_server(settings(), comfyui=fake.client())


def error_of(result) -> dict:
    assert result.is_error, result.structured_content
    text = result.content[0].text
    return json.loads(text[text.index("{") :])["error"]


# -- annotations --------------------------------------------------------------------


async def test_workflow_tools_are_annotated_honestly():
    server, _ = serve(FakeComfyUI())
    async with Client(server, mode="legacy") as client:
        tools = {t.name: t.annotations for t in (await client.list_tools()).tools}
    validate, run, outputs, upload = (
        tools[n] for n in ("workflow_validate", "workflow_run", "workflow_outputs", "workflow_upload_input")
    )
    assert validate.read_only_hint is True and outputs.read_only_hint is True
    assert (run.read_only_hint, run.destructive_hint, run.idempotent_hint) == (False, False, False)
    assert (upload.read_only_hint, upload.destructive_hint, upload.idempotent_hint) == (False, False, True)
    assert all(t.open_world_hint is False for t in (validate, run, outputs, upload))


async def test_the_workflow_tools_are_in_the_run_profile_only():
    server, _ = build_server(settings(profiles=("read",)), comfyui=FakeComfyUI().client())
    async with Client(server, mode="legacy") as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert not any(n.startswith("workflow_") for n in names)


# -- workflow_validate ----------------------------------------------------------------


async def test_validate_reports_errors_and_changes_nothing():
    fake = FakeComfyUI()
    server, _ = serve(fake)
    graph = t1()
    graph["4"]["inputs"]["images"] = ["1", 1]
    async with Client(server, mode="legacy") as client:
        got = (await client.call_tool("workflow_validate", {"workflow": graph})).structured_content
    assert (got["valid"], got["runnable"]) == (False, False)
    assert [(e["node_id"], e["input"], e["type"], e["expected"], e["got"]) for e in got["errors"]] == [
        ("4", "images", "return_type_mismatch", "IMAGE", "MASK")
    ]
    assert [c[:2] for c in fake.calls] == [("GET", "/object_info")]


async def test_validate_flags_partner_api_nodes_as_not_runnable():
    server, _ = serve(FakeComfyUI())
    graph = {
        "1": {"class_type": "ClaudeNode", "inputs": {}},
        "2": {"class_type": "PreviewAny", "inputs": {"source": ["1", 0]}},
    }
    async with Client(server, mode="legacy") as client:
        got = (await client.call_tool("workflow_validate", {"workflow": graph})).structured_content
    assert got["runnable"] is False
    assert got["partner_api_nodes"][0]["class_type"] == "ClaudeNode"


# -- workflow_run: refusals ---------------------------------------------------------------


async def test_run_refuses_partner_api_nodes_and_submits_nothing():
    fake = FakeComfyUI()
    server, relay = serve(fake)
    graph = t1()
    graph["9"] = {"class_type": "ClaudeNode", "inputs": {}}  # not even connected
    async with Client(server, mode="legacy") as client:
        error = error_of(await client.call_tool("workflow_run", {"workflow": graph}))
    assert error["code"] == "partner_api_nodes_refused" and error["retryable"] is False
    assert [(n["node_id"], n["class_type"]) for n in error["nodes"]] == [("9", "ClaudeNode")]
    assert "9 (ClaudeNode)" in error["message"]
    assert fake.posted("/prompt") == [] and relay.jobs._jobs == {}


async def test_run_refuses_an_invalid_graph_with_the_validation_errors():
    fake = FakeComfyUI()
    server, relay = serve(fake)
    graph = t1()
    graph["4"]["inputs"]["images"] = ["1", 1]
    async with Client(server, mode="legacy") as client:
        error = error_of(await client.call_tool("workflow_run", {"workflow": graph}))
        validated = (await client.call_tool("workflow_validate", {"workflow": graph})).structured_content
    assert error["code"] == "workflow_invalid"
    assert [{k: v for k, v in e.items() if v is not None} for e in validated["errors"]] == error["errors"]
    assert "node 4 (SaveImage), input 'images': return_type_mismatch" in error["message"]
    assert fake.posted("/prompt") == [] and relay.jobs._jobs == {}


async def test_run_reports_comfyuis_own_rejection():
    fake = FakeComfyUI()
    fake.reject = {
        "error": {
            "type": "prompt_outputs_failed_validation",
            "message": "Prompt outputs failed validation",
            "details": "",
        },
        "node_errors": {"1": LOADIMAGE_REJECTED},
    }
    server, relay = serve(fake)
    async with Client(server, mode="legacy") as client:
        error = error_of(await client.call_tool("workflow_run", {"workflow": t1()}))
    assert error["code"] == "workflow_rejected"
    assert error["comfyui_error"]["type"] == "prompt_outputs_failed_validation"
    assert error["node_errors"]["1"]["errors"][0]["type"] == "custom_validation_failed"
    assert error["errors"] == [  # the same shape as workflow_validate's
        {
            "type": "custom_validation_failed",
            "message": "Custom validation failed for node",
            "node_id": "1",
            "class_type": "LoadImage",
            "input": "image",
            "details": "image - Invalid image file: harness-input.png",
        }
    ]
    job = relay.jobs.get(error["job_id"])
    assert job.snapshot()["state"] == "failed" and job.error["code"] == "workflow_rejected"


async def test_outputs_comfyui_drops_are_reported_as_warnings():
    """ComfyUI accepts a graph when any output passes, and quietly drops the rest."""
    fake = FakeComfyUI(auto="hold")
    fake.accepted_node_errors = {"1": LOADIMAGE_REJECTED}
    server, _ = serve(fake)
    async with Client(server, mode="legacy") as client:
        started = (await client.call_tool("workflow_run", {"workflow": t1()})).structured_content
        await client.call_tool("job_cancel", {"job_id": started["job_id"]})
    [warning] = started["warnings"]
    assert (warning["type"], warning["node_id"], warning["input"]) == ("custom_validation_failed", "1", "image")
    assert "will not run the outputs that need this" in warning["message"]


# -- workflow_run: the job ----------------------------------------------------------------


async def test_run_returns_a_job_that_ends_with_the_saved_files():
    fake = FakeComfyUI()
    server, _ = serve(fake)
    async with Client(server, mode="legacy") as client:
        started = (await client.call_tool("workflow_run", {"workflow": t1()})).structured_content
        done = (
            await client.call_tool("job_status", {"job_id": started["job_id"], "timeout_seconds": 5})
        ).structured_content
    [submitted] = fake.posted("/prompt")
    assert submitted["prompt"] == t1()
    assert started["prompt_id"] == submitted["prompt_id"]
    assert started["comfyui_state"] in ("queued", "running", "finished")  # where it is by the time we answer
    assert started["queue_number"] == 1
    assert done["state"] == "succeeded" and done["kind"] == "workflow.run"
    assert done["result"] == {
        "prompt_id": started["prompt_id"],
        "status": "success",
        "files": [{"node_id": "4", "filename": "t1__00001_.png", "subfolder": "", "type": "output"}],
    }
    assert done["progress"]["comfyui_state"] == "finished"


async def test_job_status_shows_queue_position_then_running():
    fake = FakeComfyUI(auto="hold")
    server, _ = serve(fake)
    fake.pending.append([0, "someone-elses", {}, {}, []])
    async with Client(server, mode="legacy") as client:
        started = (await client.call_tool("workflow_run", {"workflow": t1()})).structured_content
        await asyncio.sleep(0.05)
        queued = (await client.call_tool("job_status", {"job_id": started["job_id"]})).structured_content
        fake.start(started["prompt_id"])
        await asyncio.sleep(0.05)
        running = (await client.call_tool("job_status", {"job_id": started["job_id"]})).structured_content
        fake.finish(started["prompt_id"])
        done = (
            await client.call_tool("job_status", {"job_id": started["job_id"], "timeout_seconds": 5})
        ).structured_content
    assert queued["state"] == "running"  # the job is live; where ComfyUI has it is in progress
    assert queued["progress"] == {"prompt_id": started["prompt_id"], "comfyui_state": "queued", "queue_position": 1}
    assert running["progress"]["comfyui_state"] == "running"
    assert done["state"] == "succeeded"


async def test_an_execution_error_is_the_jobs_structured_error():
    fake = FakeComfyUI(auto="error")
    server, _ = serve(fake)
    async with Client(server, mode="legacy") as client:
        started = (await client.call_tool("workflow_run", {"workflow": t1()})).structured_content
        done = (
            await client.call_tool("job_status", {"job_id": started["job_id"], "timeout_seconds": 5})
        ).structured_content
    assert done["state"] == "failed"
    error = done["error"]
    assert error["code"] == "workflow_execution_failed" and error["retryable"] is False
    assert (error["node_id"], error["node_type"], error["exception_type"]) == ("2", "ImageToMask", "IndexError")
    assert error["message"] == (
        "node 2 (ImageToMask) failed while running: IndexError: index 3 is out of bounds for dimension 3 with size 3"
    )
    assert error["traceback_tail"] == "  File b\n  File c\n"
    assert "current_inputs" not in error


async def test_an_interrupt_from_elsewhere_is_reported_as_such():
    fake = FakeComfyUI(auto="hold")
    work = tw.run_prompt(fake.client(), t1(), {"prompt_id": "p1", "comfyui_state": "submitting"})
    task = asyncio.ensure_future(work)
    await asyncio.sleep(0.05)
    fake.finish("p1", "error", [["execution_interrupted", {"node_id": "3", "node_type": "ImageInvert"}]])
    with pytest.raises(tw.RelayError) as info:
        await asyncio.wait_for(task, 5)
    assert info.value.code == "workflow_interrupted" and info.value.detail["node_id"] == "3"


async def test_a_prompt_that_vanishes_fails_the_job():
    fake = FakeComfyUI(auto="hold")
    task = asyncio.ensure_future(tw.run_prompt(fake.client(), t1(), {"prompt_id": "p1"}))
    await asyncio.sleep(0.05)
    fake.pending.clear()  # someone else deleted it
    with pytest.raises(tw.RelayError) as info:
        await asyncio.wait_for(task, 5)
    assert info.value.code == "workflow_vanished"


async def test_comfyui_blinking_out_is_ridden_out():
    fake = FakeComfyUI(auto="hold")
    task = asyncio.ensure_future(tw.run_prompt(fake.client(), t1(), progress := {"prompt_id": "p1"}))
    await asyncio.sleep(0.05)
    fake.down = True
    await asyncio.sleep(0.05)
    assert "could not reach ComfyUI" in progress["comfyui_error"] and not task.done()
    fake.down = False
    fake.finish("p1")
    assert (await asyncio.wait_for(task, 5))["status"] == "success"
    assert "comfyui_error" not in progress


# -- cancellation: the producer contract -----------------------------------------------------


async def test_cancelling_a_queued_run_dequeues_it_and_interrupts_nothing():
    fake = FakeComfyUI(auto="hold")
    started = asyncio.Event()
    progress = {"prompt_id": "p-queued"}

    async def work():
        submitted = asyncio.get_running_loop().create_future()
        submitted.add_done_callback(lambda _f: started.set())
        return await tw.run_prompt(fake.client(), t1(), progress, submitted)

    await assert_producer_honours_cancel(work, started=started)
    assert fake.posted("/queue") == [{"delete": ["p-queued"]}]
    assert fake.posted("/interrupt") == []
    assert fake.pending == [] and "p-queued" not in fake.history


async def test_cancelling_a_running_run_interrupts_that_prompt_only():
    fake = FakeComfyUI(auto="hold")
    started = asyncio.Event()
    progress = {"prompt_id": "p-running"}

    async def work():
        submitted = asyncio.get_running_loop().create_future()
        submitted.add_done_callback(lambda _f: (fake.start("p-running"), started.set()))
        return await tw.run_prompt(fake.client(), t1(), progress, submitted)

    await assert_producer_honours_cancel(work, started=started)
    assert fake.posted("/interrupt") == [{"prompt_id": "p-running"}]
    assert fake.history["p-running"]["status"]["messages"][0][0] == "execution_interrupted"


async def test_a_run_elsewhere_is_never_interrupted():
    fake = FakeComfyUI(auto="hold")
    fake.running.append([0, "someone-elses", {}, {}, []])
    started = asyncio.Event()

    async def work():
        submitted = asyncio.get_running_loop().create_future()
        submitted.add_done_callback(lambda _f: started.set())
        return await tw.run_prompt(fake.client(), t1(), {"prompt_id": "mine"}, submitted)

    await assert_producer_honours_cancel(work, started=started)
    assert fake.posted("/interrupt") == []
    assert fake.running[0][1] == "someone-elses"


async def test_cancelling_holds_its_budget_when_comfyui_hangs():
    fake = FakeComfyUI(auto="hold")
    started = asyncio.Event()

    async def work():
        submitted = asyncio.get_running_loop().create_future()
        submitted.add_done_callback(lambda _f: (fake.slow.add("/queue"), started.set()))
        return await tw.run_prompt(fake.client(), t1(), {"prompt_id": "p"}, submitted)

    await assert_producer_honours_cancel(work, started=started)  # within 3s, though ComfyUI never answers


async def test_cancelling_before_comfyui_answered_the_submission_still_cleans_up():
    fake = FakeComfyUI(auto="hold")
    fake.slow.add("/prompt")
    await assert_producer_honours_cancel(lambda: tw.run_prompt(fake.client(), t1(), {"prompt_id": "p-early"}))
    assert fake.posted("/queue") == [{"delete": ["p-early"]}]


async def test_job_cancel_through_the_tools():
    fake = FakeComfyUI(auto="hold")
    server, _ = serve(fake)
    async with Client(server, mode="legacy") as client:
        started = (await client.call_tool("workflow_run", {"workflow": t1()})).structured_content
        fake.start(started["prompt_id"])
        await asyncio.sleep(0.05)
        cancelled = (await client.call_tool("job_cancel", {"job_id": started["job_id"]})).structured_content
    assert cancelled["state"] == "cancelled" and cancelled["result"] is None
    assert fake.posted("/interrupt") == [{"prompt_id": started["prompt_id"]}]


# -- workflow_outputs ---------------------------------------------------------------------------


async def finished_job(client) -> str:
    started = (await client.call_tool("workflow_run", {"workflow": t1()})).structured_content
    await client.call_tool("job_status", {"job_id": started["job_id"], "timeout_seconds": 5})
    return started["job_id"]


async def test_outputs_lists_files_with_sizes_and_streams_nothing_by_default():
    fake = FakeComfyUI()
    server, _ = serve(fake)
    async with Client(server, mode="legacy") as client:
        job_id = await finished_job(client)
        got = await client.call_tool("workflow_outputs", {"job_id": job_id})
    assert not got.is_error
    [file] = got.structured_content["files"]
    assert file == {
        "node_id": "4",
        "kind": "images",
        "filename": "t1__00001_.png",
        "subfolder": "",
        "type": "output",
        "size_bytes": len(PNG),
        "mime_type": "image/png",
        "view_path": "/view?filename=t1__00001_.png&subfolder=&type=output",
    }
    assert got.structured_content["fetched"] is None
    assert [c.type for c in got.content] == ["text"]
    assert ("GET", "/view") not in [c[:2] for c in fake.calls]


async def test_outputs_fetches_one_file_inline():
    fake = FakeComfyUI()
    server, _ = serve(fake)
    async with Client(server, mode="legacy") as client:
        job_id = await finished_job(client)
        got = await client.call_tool("workflow_outputs", {"job_id": job_id, "fetch": "t1__00001_.png"})
    assert got.structured_content["fetched"] == "t1__00001_.png"
    image = got.content[1]
    assert image.type == "image" and image.mime_type == "image/png"
    assert base64.b64decode(image.data) == PNG


async def test_outputs_refuses_a_file_over_the_inline_cap(monkeypatch):
    monkeypatch.setattr(tw, "MAX_INLINE_BYTES", 10)
    fake = FakeComfyUI()
    server, _ = serve(fake)
    async with Client(server, mode="legacy") as client:
        job_id = await finished_job(client)
        error = error_of(await client.call_tool("workflow_outputs", {"job_id": job_id, "fetch": "t1__00001_.png"}))
    assert error["code"] == "output_too_large" and error["size_bytes"] == len(PNG)
    assert "/view?filename=t1__00001_.png" in error["message"]


async def test_outputs_of_an_unknown_file_names_the_files_there_are():
    fake = FakeComfyUI()
    server, _ = serve(fake)
    async with Client(server, mode="legacy") as client:
        job_id = await finished_job(client)
        error = error_of(await client.call_tool("workflow_outputs", {"job_id": job_id, "fetch": "nope.png"}))
    assert error["code"] == "unknown_output" and error["expected"] == ["t1__00001_.png"]


async def test_outputs_of_an_unfinished_job_says_to_wait():
    fake = FakeComfyUI(auto="hold")
    server, _ = serve(fake)
    async with Client(server, mode="legacy") as client:
        started = (await client.call_tool("workflow_run", {"workflow": t1()})).structured_content
        error = error_of(await client.call_tool("workflow_outputs", {"job_id": started["job_id"]}))
        await client.call_tool("job_cancel", {"job_id": started["job_id"]})
    assert error["code"] == "job_not_finished" and error["retryable"] is True


async def test_outputs_of_a_job_that_is_not_a_run():
    fake = FakeComfyUI()
    server, relay = serve(fake)
    other = relay.jobs.submit("test.other", lambda: asyncio.sleep(0))
    async with Client(server, mode="legacy") as client:
        error = error_of(await client.call_tool("workflow_outputs", {"job_id": other.id}))
    assert error["code"] == "not_a_workflow_job"


# -- workflow_upload_input ----------------------------------------------------------------------


async def upload(fake, filename, data: bytes | str):
    server, _ = serve(fake)
    content = data if isinstance(data, str) else base64.b64encode(data).decode()
    async with Client(server, mode="legacy") as client:
        return await client.call_tool("workflow_upload_input", {"filename": filename, "content_base64": content})


async def test_upload_stores_into_the_input_directory_and_reports_the_name():
    fake = FakeComfyUI()
    got = await upload(fake, "photo.png", PNG)
    assert got.structured_content == {
        "name": "photo.png",
        "subfolder": "",
        "type": "input",
        "size_bytes": len(PNG),
        "requested_name": "photo.png",
        "renamed": False,
    }
    again = await upload(fake, "photo.png", PNG + b"x")
    assert (again.structured_content["name"], again.structured_content["renamed"]) == ("photo (1).png", True)


@pytest.mark.parametrize(
    ("given", "stored"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\me\\cat.png", "cat.png"),
        (".hidden.png", "hidden.png"),
        ("a b?*<>|.png", "a b_____.png"),
        ("日本.png", "__.png"),
        ("x" * 300 + ".png", "x" * 116 + ".png"),
    ],
)
async def test_upload_sanitises_the_name(given, stored):
    assert tw.sanitise_filename(given) == stored
    got = await upload(FakeComfyUI(), given, PNG)
    assert got.structured_content["name"] == stored


@pytest.mark.parametrize("name", ["", "..", "../", "/", "...", "__"])
async def test_upload_refuses_a_name_with_nothing_left(name):
    fake = FakeComfyUI()
    error = error_of(await upload(fake, name, PNG))
    assert error["code"] == "invalid_filename"
    assert fake.posted("/upload/image") == [] and ("POST", "/upload/image") not in [c[:2] for c in fake.calls]


async def test_upload_refuses_a_file_over_the_cap(monkeypatch):
    monkeypatch.setattr(tw, "MAX_UPLOAD_BYTES", 16)
    fake = FakeComfyUI()
    error = error_of(await upload(fake, "big.png", b"x" * 17))
    assert error["code"] == "upload_too_large" and (error["limit"], error["size_bytes"]) == (16, 17)
    assert ("POST", "/upload/image") not in [c[:2] for c in fake.calls]


async def test_upload_refuses_base64_past_the_schema_limit():
    fake = FakeComfyUI()
    too_long = "A" * ((tw.MAX_UPLOAD_BYTES + 2) // 3 * 4 + 104)
    got = await upload(fake, "big.png", too_long)
    assert got.is_error
    assert ("POST", "/upload/image") not in [c[:2] for c in fake.calls]


async def test_upload_accepts_a_data_url_and_refuses_bad_base64():
    fake = FakeComfyUI()
    ok = await upload(fake, "p.png", "data:image/png;base64," + base64.b64encode(PNG).decode())
    assert ok.structured_content["size_bytes"] == len(PNG)
    assert error_of(await upload(fake, "p.png", "not base64!"))["code"] == "invalid_base64"
    assert error_of(await upload(fake, "p.png", ""))["code"] == "empty_upload"
