"""The workflow tools and the run producer, against a fake ComfyUI that keeps a queue and a history the way
ComfyUI does. The real-ComfyUI counterpart is test_relay_workflow_live.py."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid

import comfyrelay.tools_workflow as tw
import httpx2
import pytest
from comfyrelay.comfyui import ComfyUIClient
from comfyrelay.jobs import JobStore
from comfyrelay.server import build_server
from mcp import Client
from relay_helpers import (
    SYSTEM_STATS,
    TOKEN,
    WORKFLOW_OBJECT_INFO,
    assert_producer_honours_cancel,
    free_port,
    settings,
)

pytestmark = pytest.mark.anyio

INFO = WORKFLOW_OBJECT_INFO
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
    """Just enough of ComfyUI's HTTP API, as v0.37.0 behaves: /object_info, /prompt, /queue, /history,
    /api/jobs/<id> and its atomic /cancel, /upload/image, /view. /interrupt is recorded but never acted on:
    comfyrelay must not send it.

    `auto` decides what happens to a submitted prompt: "success" finishes it at the next status poll, "error"
    fails it at node 2, "hold" leaves it queued until the test calls start() or finish().
    `delays` holds a path's answer back that many seconds; ComfyUI still does the work afterwards, as it does for
    a client that hung up. `jobs_api=False` is a ComfyUI without /api/jobs. `stubborn` running prompts ignore a
    cancel (a node that never reaches a boundary)."""

    def __init__(self, auto: str = "success") -> None:
        self.auto = auto
        self.running: list[list] = []
        self.pending: list[list] = []
        self.history: dict[str, dict] = {}
        self.calls: list[tuple[str, str, object]] = []
        self.number = 0
        self.reject: dict | None = None
        self.accepted_node_errors: dict = {}
        self.files = {"t1__00001_.png": PNG, "t1__00002_.png": PNG}
        self.stored: dict[str, bytes] = {}
        self.delays: dict[str, float] = {}
        self.jobs_api = True
        self.outputs = SAVED
        self.stubborn = False
        self.lost_interrupts = 0  # interrupts ComfyUI drops: one landing as a prompt starts is cleared by it
        self.finish_on_cancel = False  # a running prompt completes before the interrupt reaches a node boundary
        self.before_cancel = None  # called with the prompt id as a cancel reaches ComfyUI: it gets there first
        self.fail_once: set[str] = set()  # paths whose next request fails with a reset connection
        self.fail_status: dict[str, int] = {}  # paths answered with this HTTP status, for as long as they are set
        self.mint_ids = False  # answer /prompt with an id of ComfyUI's own, as older ComfyUIs do
        self.job_polls = 0
        self.absent_polls: set[int] = set()  # GET /api/jobs/<id> calls (1-based) answered "Job not found"
        self.uploading = 0
        self.max_uploading = 0
        self.down = False  # nothing answers at all

    def client(self) -> ComfyUIClient:
        return ComfyUIClient("http://comfyui.test:8188", transport=httpx2.MockTransport(self.handle))

    def posted(self, path: str) -> list:
        return [body for method, p, body in self.calls if method == "POST" and p == path]

    def count(self, method: str, prefix: str) -> int:
        return sum(1 for m, p, _ in self.calls if m == method and p.startswith(prefix))

    def start(self, prompt_id: str) -> None:
        item = next(i for i in self.pending if i[1] == prompt_id)
        self.pending.remove(item)
        self.running.append(item)

    def finish(self, prompt_id: str, status: str = "success", messages: list | None = None, outputs=None) -> None:
        item = next((i for i in (*self.running, *self.pending) if i[1] == prompt_id), [0, prompt_id, {}, {}, []])
        for queue in (self.running, self.pending):
            queue[:] = [i for i in queue if i[1] != prompt_id]
        self.history[prompt_id] = {
            "prompt": item[:5],
            "outputs": self.outputs if outputs is None else outputs,
            "status": {"status_str": status, "completed": status == "success", "messages": messages or []},
        }

    def job(self, prompt_id: str, status: str) -> dict:
        """GET /api/jobs/<id>'s answer (v0.37.0 get_job): small while live, the full entry once it has ended."""
        if status in ("pending", "in_progress"):
            item = next(i for i in (*self.running, *self.pending) if i[1] == prompt_id)
            return {"id": prompt_id, "status": status, "create_time": item[3].get("create_time")}
        entry = self.history[prompt_id]
        return {
            "id": prompt_id,
            "status": status,
            "create_time": entry["prompt"][3].get("create_time"),
            "execution_start_time": 1_790_000_001_000,
            "execution_end_time": 1_790_000_002_000,
            "outputs": entry["outputs"],
            "execution_status": entry["status"],
            "workflow": {"prompt": entry["prompt"][2], "extra_data": entry["prompt"][3]},
        }

    def _advance(self) -> None:
        for item in list(self.pending):
            if self.auto == "success":
                self.finish(item[1])
            elif self.auto == "error":
                self.finish(item[1], "error", [["execution_error", RUNTIME_ERROR]], outputs={})

    def _status(self, prompt_id: str) -> str | None:
        if prompt_id in self.history:
            messages = [m[0] for m in self.history[prompt_id]["status"]["messages"]]
            if self.history[prompt_id]["status"]["status_str"] == "success":
                return "completed"
            return "cancelled" if "execution_interrupted" in messages else "failed"
        if any(i[1] == prompt_id for i in self.running):
            return "in_progress"
        if any(i[1] == prompt_id for i in self.pending):
            return "pending"
        return None

    async def handle(self, request: httpx2.Request) -> httpx2.Response:
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.headers.get("content-type") == "application/json" else None
        if self.down:
            raise httpx2.ConnectError("refused", request=request)
        if path in self.fail_once:
            self.fail_once.discard(path)
            raise httpx2.RemoteProtocolError("connection reset", request=request)
        self.calls.append((method, path, body))
        if path in self.fail_status:
            return httpx2.Response(self.fail_status[path])
        if path in self.delays:
            await asyncio.sleep(self.delays[path])
        if path == "/system_stats":
            return httpx2.Response(200, json=SYSTEM_STATS)
        if path == "/object_info":
            return httpx2.Response(200, json=INFO)
        if (method, path) == ("POST", "/prompt"):
            if self.reject is not None:
                return httpx2.Response(400, json=self.reject)
            self.number += 1
            prompt_id = f"minted-{self.number}" if self.mint_ids else body["prompt_id"]
            extra_data = {"client_id": body["client_id"]} if "client_id" in body else {}
            extra_data["create_time"] = 1_790_000_000_000 + self.number
            self.pending.append([self.number, prompt_id, body["prompt"], extra_data, []])
            return httpx2.Response(
                200,
                json={"prompt_id": prompt_id, "number": self.number, "node_errors": self.accepted_node_errors},
            )
        if path.startswith("/api/jobs/") and not self.jobs_api:
            return httpx2.Response(404, text="404: Not Found", headers={"content-type": "application/octet-stream"})
        if method == "POST" and path.startswith("/api/jobs/") and path.endswith("/cancel"):
            prompt_id = path.split("/")[3]
            if self.before_cancel is not None and self._status(prompt_id) in ("pending", "in_progress"):
                self.before_cancel(prompt_id)
            status = self._status(prompt_id)
            if status == "pending":
                self.pending[:] = [i for i in self.pending if i[1] != prompt_id]
            elif status == "in_progress" and self.lost_interrupts:
                self.lost_interrupts -= 1
            elif status == "in_progress" and self.finish_on_cancel:
                self.finish(prompt_id)  # it got there first
                return httpx2.Response(200, json={"cancelled": True})
            elif status == "in_progress" and not self.stubborn:
                self.finish(prompt_id, "error", [["execution_interrupted", {"node_id": "3", "node_type": "X"}]])
            return httpx2.Response(200, json={"cancelled": status in ("pending", "in_progress")})
        if method == "GET" and path.startswith("/api/jobs/"):
            self._advance()
            prompt_id = path.split("/")[3]
            status = self._status(prompt_id)
            self.job_polls += 1
            if status is None or self.job_polls in self.absent_polls:
                return httpx2.Response(404, json={"error": "Job not found"})
            return httpx2.Response(200, json=self.job(prompt_id, status))
        if (method, path) == ("GET", "/queue"):
            self._advance()
            return httpx2.Response(200, json={"queue_running": self.running, "queue_pending": self.pending})
        if (method, path) == ("POST", "/queue"):
            for prompt_id in body.get("delete", []):
                self.pending[:] = [i for i in self.pending if i[1] != prompt_id]
            return httpx2.Response(200)
        if (method, path) == ("POST", "/interrupt"):
            return httpx2.Response(200)  # recorded above; tests assert it never comes
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
            self.uploading += 1
            self.max_uploading = max(self.max_uploading, self.uploading)
            await asyncio.sleep(self.delays.get("upload", 0))
            self.uploading -= 1
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


@pytest.fixture
def quick_stop(monkeypatch):
    """The stop's timings at a third or less, for the tests that wait them out: a 0.8s budget with 0.3s of it
    kept for the cancel, and checks and settling every 0.05s. The delays those tests set scale with them."""
    monkeypatch.setattr(tw, "STOP_BUDGET_SECONDS", 0.8)
    monkeypatch.setattr(tw, "CANCEL_RESERVE_SECONDS", 0.3)
    monkeypatch.setattr(tw, "STOP_CHECK_SECONDS", 0.05)
    monkeypatch.setattr(tw, "SETTLE_SECONDS", 0.05)


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
    graph["3"]["class_type"] = "ImageInvertt"
    async with Client(server, mode="legacy") as client:
        got = (await client.call_tool("workflow_validate", {"workflow": graph})).structured_content
    assert (got["valid"], got["runnable"]) == (False, False)
    assert [(e["node_id"], e["class_type"], e["type"], e["expected"]) for e in got["errors"]] == [
        ("3", "ImageInvertt", "missing_node_type", ["ImageInvert"])
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
    graph["3"]["class_type"] = "ImageInvertt"
    async with Client(server, mode="legacy") as client:
        error = error_of(await client.call_tool("workflow_run", {"workflow": graph}))
        validated = (await client.call_tool("workflow_validate", {"workflow": graph})).structured_content
    assert error["code"] == "workflow_invalid"
    assert [{k: v for k, v in e.items() if v is not None} for e in validated["errors"]] == error["errors"]
    assert "node 3 (ImageInvertt): missing_node_type" in error["message"]
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


def producer(fake: FakeComfyUI, progress: dict, started: asyncio.Event, then=None):
    """The run producer, with `started` set once ComfyUI has answered the submission (after `then()`)."""

    async def work():
        submitted = asyncio.get_running_loop().create_future()
        submitted.add_done_callback(lambda _f: ((then or (lambda: None))(), started.set()))
        return await tw.run_prompt(fake.client(), t1(), progress, submitted)

    return work


async def test_cancelling_a_queued_run_uses_the_atomic_cancel_and_confirms():
    fake = FakeComfyUI(auto="hold")
    started, progress = asyncio.Event(), {"prompt_id": "p-queued"}
    await assert_producer_honours_cancel(producer(fake, progress, started), started=started)
    assert fake.count("POST", "/api/jobs/p-queued/cancel") == 1
    assert fake.posted("/interrupt") == [] and fake.posted("/queue") == []
    assert fake.pending == [] and "p-queued" not in fake.history
    assert progress["stop"] == "confirmed"


async def test_cancelling_a_running_run_stops_it_and_confirms():
    fake = FakeComfyUI(auto="hold")
    started, progress = asyncio.Event(), {"prompt_id": "p-running"}
    await assert_producer_honours_cancel(
        producer(fake, progress, started, then=lambda: fake.start("p-running")), started=started
    )
    assert fake.posted("/interrupt") == []
    assert fake.history["p-running"]["status"]["messages"][0][0] == "execution_interrupted"
    assert progress["stop"] == "confirmed"


@pytest.mark.usefixtures("quick_stop")
async def test_a_stop_comfyui_does_not_confirm_in_time_is_unconfirmed():
    fake = FakeComfyUI(auto="hold")
    fake.stubborn = True  # the running node never reaches a boundary
    started, progress = asyncio.Event(), {"prompt_id": "p"}
    await assert_producer_honours_cancel(
        producer(fake, progress, started, then=lambda: fake.start("p")), started=started
    )
    assert progress["stop"] == "unconfirmed" and "in_progress" in progress["stop_detail"]
    assert fake.count("POST", "/api/jobs/p/cancel") > 3  # sent again at every check


async def test_an_interrupt_comfyui_drops_is_sent_again():
    """ComfyUI clears its interrupt flag as a prompt starts executing, so a cancel landing just then is lost."""
    fake = FakeComfyUI(auto="hold")
    fake.lost_interrupts = 1
    started, progress = asyncio.Event(), {"prompt_id": "p"}
    await assert_producer_honours_cancel(
        producer(fake, progress, started, then=lambda: fake.start("p")), started=started
    )
    assert fake.count("POST", "/api/jobs/p/cancel") == 2
    assert progress["stop"] == "confirmed" and fake.running == []


async def test_a_run_elsewhere_is_never_touched():
    fake = FakeComfyUI(auto="hold")
    fake.running.append([0, "someone-elses", {}, {}, []])
    started, progress = asyncio.Event(), {"prompt_id": "mine"}
    await assert_producer_honours_cancel(producer(fake, progress, started), started=started)
    assert fake.posted("/interrupt") == []
    assert [c for c in fake.calls if "someone-elses" in c[1]] == []
    assert fake.running[0][1] == "someone-elses"


async def test_without_the_jobs_api_a_queued_run_is_dequeued():
    fake = FakeComfyUI(auto="hold")
    fake.jobs_api = False
    started, progress = asyncio.Event(), {"prompt_id": "p"}
    await assert_producer_honours_cancel(producer(fake, progress, started), started=started)
    assert fake.posted("/queue") == [{"delete": ["p"]}] and fake.pending == []
    assert progress["stop"] == "confirmed"


async def test_without_the_jobs_api_a_running_run_is_never_interrupted():
    """No atomic cancel: /interrupt could land on someone else's prompt, so the run is left, and said so."""
    fake = FakeComfyUI(auto="hold")
    fake.jobs_api = False
    started, progress = asyncio.Event(), {"prompt_id": "p"}
    await assert_producer_honours_cancel(
        producer(fake, progress, started, then=lambda: fake.start("p")), started=started
    )
    assert fake.posted("/interrupt") == []
    assert fake.running[0][1] == "p"
    assert progress["stop"] == "not_stopped" and "no atomic cancel" in progress["stop_detail"]


@pytest.mark.usefixtures("quick_stop")
async def test_cancelling_holds_its_budget_when_comfyui_hangs():
    fake = FakeComfyUI(auto="hold")
    started, progress = asyncio.Event(), {"prompt_id": "p"}
    hang = lambda: fake.delays.update({"/api/jobs/p/cancel": 30})  # noqa: E731
    await assert_producer_honours_cancel(producer(fake, progress, started, then=hang), started=started)
    assert progress["stop"] == "unconfirmed"


async def test_a_cancel_during_submission_waits_for_the_answer_then_cancels():
    """ComfyUI finishes a /prompt whose client hung up. The stop must come after it, or it misses the prompt."""
    fake = FakeComfyUI(auto="hold")
    fake.delays["/prompt"] = 0.5
    progress = {"prompt_id": "p-early"}
    await assert_producer_honours_cancel(lambda: tw.run_prompt(fake.client(), t1(), progress))
    order = [(m, p) for m, p, _ in fake.calls if p in ("/prompt", "/api/jobs/p-early/cancel")]
    assert order == [("POST", "/prompt"), ("POST", "/api/jobs/p-early/cancel")]
    assert fake.pending == [] and fake.running == [] and progress["stop"] == "confirmed"


@pytest.mark.usefixtures("quick_stop")
async def test_a_submission_slower_than_the_budget_is_cancelled_when_it_answers(caplog):
    caplog.set_level(logging.INFO, logger="comfyrelay.workflow")
    fake = FakeComfyUI(auto="hold")
    fake.delays["/prompt"] = 1.0  # past what the unwind may wait (0.8s budget less the 0.3s reserve)
    progress = {"prompt_id": "p-late"}
    await assert_producer_honours_cancel(lambda: tw.run_prompt(fake.client(), t1(), progress))
    assert progress["stop"] == "unconfirmed" and "cancelled again" in progress["stop_detail"]
    await asyncio.sleep(0.8)  # ComfyUI answers and queues it; the late cancel follows
    assert fake.pending == [] and fake.count("POST", "/api/jobs/p-late/cancel") == 2
    assert "stop of prompt p-late, carried on because its submission was answered" in caplog.text
    assert "p-late" in caplog.text and ": stopped" in caplog.text
    assert progress["stop"] == "confirmed" and "stop_detail" not in progress  # job_status caught up


async def test_a_second_cancel_does_not_abort_the_stop():
    """R1: job_cancel twice. The second must not land a CancelledError inside the first one's cleanup."""
    fake = FakeComfyUI(auto="hold")
    fake.delays["/api/jobs/p/cancel"] = 0.3
    started, progress = asyncio.Event(), {"prompt_id": "p"}
    store = JobStore()
    job = store.submit(tw.RUN_KIND, producer(fake, progress, started, then=lambda: fake.start("p")))
    await asyncio.wait_for(started.wait(), 5)
    first = asyncio.ensure_future(store.cancel(job.id))
    await asyncio.sleep(0.1)  # the first stop is under way
    await store.cancel(job.id)
    await first
    assert job.state.value == "cancelled" and job.cancel_reason == "cancel"
    assert fake.running == [] and fake.history["p"]["status"]["messages"][0][0] == "execution_interrupted"
    assert progress["stop"] == "confirmed"


async def test_a_shutdown_during_a_cancel_does_not_undo_it():
    fake = FakeComfyUI(auto="hold")
    fake.delays["/api/jobs/p/cancel"] = 0.3
    started, progress = asyncio.Event(), {"prompt_id": "p"}
    store = JobStore()
    job = store.submit(tw.RUN_KIND, producer(fake, progress, started, then=lambda: fake.start("p")))
    await asyncio.wait_for(started.wait(), 5)
    cancelling = asyncio.ensure_future(store.cancel(job.id))
    await asyncio.sleep(0.1)
    assert await store.shutdown() == []
    await cancelling
    assert job.cancel_reason == "cancel" and progress["stop"] == "confirmed"
    assert fake.running == [] and "p" in fake.history


async def test_a_shutdown_leaves_the_prompt_running():
    """Owner decision on #145: a stopping relay does not stop its runs; a restarted one re-attaches (#146)."""
    fake = FakeComfyUI(auto="hold")
    started, progress = asyncio.Event(), {"prompt_id": "p"}
    store = JobStore()
    job = store.submit(tw.RUN_KIND, producer(fake, progress, started, then=lambda: fake.start("p")))
    await asyncio.wait_for(started.wait(), 5)
    assert await asyncio.wait_for(store.shutdown(), 3.5) == []
    assert job.state.value == "cancelled" and job.cancel_reason == "shutdown"
    assert progress["stop"] == "left_running"
    assert fake.count("POST", "/api/jobs/") == 0 and fake.posted("/queue") == [] and fake.posted("/interrupt") == []
    assert fake.running[0][1] == "p"


async def test_job_cancel_through_the_tools_reports_the_stop():
    fake = FakeComfyUI(auto="hold")
    server, _ = serve(fake)
    async with Client(server, mode="legacy") as client:
        started = (await client.call_tool("workflow_run", {"workflow": t1()})).structured_content
        fake.start(started["prompt_id"])
        await asyncio.sleep(0.05)
        cancelled = (await client.call_tool("job_cancel", {"job_id": started["job_id"]})).structured_content
    assert cancelled["state"] == "cancelled" and cancelled["result"] is None
    assert cancelled["progress"]["stop"] == "confirmed"
    assert fake.count("POST", f"/api/jobs/{started['prompt_id']}/cancel") == 1 and fake.posted("/interrupt") == []


# -- polling: the jobs API, and one shared /queue ----------------------------------------------


async def test_a_running_prompt_is_followed_through_the_jobs_api_not_queue():
    fake = FakeComfyUI(auto="hold")
    fake.pending.append([0.5, "p", {}, {}, []])
    fake.start("p")
    task = asyncio.ensure_future(tw._follow(fake.client(), {"prompt_id": "p"}))
    await asyncio.sleep(0.2)
    fake.finish("p")
    assert (await asyncio.wait_for(task, 5))["status"] == "success"
    assert fake.count("GET", "/queue") == 0 and fake.count("GET", "/api/jobs/p") > 3


async def test_queue_position_comes_from_one_shared_throttled_queue_read():
    fake = FakeComfyUI(auto="hold")
    client = fake.client()
    # ComfyUI's numbers are floats (front-of-queue ones negative); order them as numbers, not as strings.
    fake.pending += [[10.0, "b", {}, {}, []], [9, "a", {}, {}, []], [-1.0, "front", {}, {}, []], [11, "c", {}, {}, []]]
    pb, pc = {"prompt_id": "b"}, {"prompt_id": "c"}
    runs = [asyncio.ensure_future(tw._follow(client, p)) for p in (pb, pc)]
    await asyncio.sleep(0.3)  # about 30 polls each at the test's 0.01s
    assert (pb["queue_position"], pc["queue_position"]) == (2, 3)
    assert fake.count("GET", "/queue") == 1  # shared between both runs, and held for QUEUE_TTL_SECONDS
    for run in runs:
        run.cancel()
    await asyncio.gather(*runs, return_exceptions=True)


async def test_without_the_jobs_api_it_follows_through_queue_and_history():
    fake = FakeComfyUI(auto="success")
    fake.jobs_api = False
    task = asyncio.ensure_future(tw.run_prompt(fake.client(), t1(), {"prompt_id": "p"}))
    assert (await asyncio.wait_for(task, 5))["status"] == "success"
    assert fake.count("GET", "/queue") >= 1


# -- the spend backstop ---------------------------------------------------------------------------


async def test_the_prompt_request_carries_no_extra_data():
    """Partner-API nodes get the user's Comfy.org credentials only from /prompt's extra_data, which this server
    never sends: a backstop behind the refusal. The body is exactly the graph, the relay's prompt id, and its
    client_id, a plain name with no credential in it, which lets a restarted relay prove a prompt is its own (#146)."""
    fake = FakeComfyUI()
    server, _ = serve(fake)
    async with Client(server, mode="legacy") as client:
        await client.call_tool("workflow_run", {"workflow": t1()})
    [body] = fake.posted("/prompt")
    assert set(body) == {"prompt", "prompt_id", "client_id"}
    assert "extra_data" not in body
    assert body["client_id"] == "comfyrelay:test-instance"


# -- workflow_outputs ---------------------------------------------------------------------------


TWO_SAVED = {
    "4": {"images": [SAVED["4"]["images"][0], {"filename": "t1__00002_.png", "subfolder": "", "type": "output"}]}
}


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


async def test_outputs_fetches_one_file_inline_and_sizes_only_that_one():
    fake = FakeComfyUI()
    server, _ = serve(fake)
    async with Client(server, mode="legacy") as client:
        fake.outputs = TWO_SAVED
        job_id = await finished_job(client)
        heads = fake.count("HEAD", "/view")
        got = await client.call_tool("workflow_outputs", {"job_id": job_id, "fetch": "t1__00001_.png"})
    assert fake.count("HEAD", "/view") - heads == 1
    assert [f["size_bytes"] for f in got.structured_content["files"]] == [len(PNG), None]
    assert tw.MAX_INLINE_BYTES == 5_000_000
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


async def test_upload_refuses_base64_past_the_cap_before_decoding_it():
    fake = FakeComfyUI()
    too_long = "A" * (tw.MAX_UPLOAD_BASE64_CHARS + 4)
    assert error_of(await upload(fake, "big.png", too_long))["code"] == "upload_too_large"
    assert ("POST", "/upload/image") not in [c[:2] for c in fake.calls]


async def test_upload_accepts_line_wrapped_base64():
    fake = FakeComfyUI()
    encoded = base64.encodebytes(PNG * 4).decode()  # MIME style: a line break every 76 characters
    assert "\n" in encoded
    got = await upload(fake, "wrapped.png", " " + encoded.replace("\n", "\r\n\t"))
    assert got.structured_content["size_bytes"] == len(PNG) * 4


async def test_upload_accepts_a_data_url_and_refuses_bad_base64():
    fake = FakeComfyUI()
    ok = await upload(fake, "p.png", "data:image/png;base64," + base64.b64encode(PNG).decode())
    assert ok.structured_content["size_bytes"] == len(PNG)
    assert error_of(await upload(fake, "p.png", "not base64!"))["code"] == "invalid_base64"
    assert error_of(await upload(fake, "p.png", ""))["code"] == "empty_upload"


async def test_object_info_is_shared_briefly_and_dropped_after_an_upload():
    fake = FakeComfyUI()
    server, _ = serve(fake)
    async with Client(server, mode="legacy") as client:
        for _ in range(3):
            await client.call_tool("workflow_validate", {"workflow": t1()})
        assert fake.count("GET", "/object_info") == 1
        await client.call_tool(
            "workflow_upload_input", {"filename": "new.png", "content_base64": base64.b64encode(PNG).decode()}
        )
        await client.call_tool("workflow_validate", {"workflow": t1()})
    assert fake.count("GET", "/object_info") == 2  # LoadImage's file list changed


# -- uploads over the real HTTP transport ---------------------------------------------------------


@pytest.fixture
def http_relay():
    """comfyrelay over real HTTP (the transport's body limit applies), in front of a FakeComfyUI."""
    import threading
    import time

    import uvicorn
    from comfyrelay.server import http_app

    fake = FakeComfyUI()
    s = settings(port=free_port())
    server, _ = build_server(s, comfyui=fake.client())
    uv = uvicorn.Server(uvicorn.Config(http_app(server, s), host=s.host, port=s.port, log_config=None))
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not uv.started:
        assert time.time() < deadline, "the test server did not start"
        time.sleep(0.05)
    yield f"http://{s.host}:{s.port}/mcp", fake
    uv.should_exit = True
    thread.join(10)


@pytest.mark.parametrize(
    ("size", "code"),
    [
        (3_300_000, None),  # past the SDK's default 4 MiB body once base64-encoded: refused with a bare 413 before
        (tw.MAX_UPLOAD_BYTES, None),
        (tw.MAX_UPLOAD_BYTES + 1, "upload_too_large"),
    ],
)
async def test_upload_size_boundary_over_http(http_relay, size, code):
    from mcp.client.streamable_http import streamable_http_client

    url, fake = http_relay
    content = base64.b64encode(b"\x00" * size).decode()
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"}, timeout=60) as http:
        async with Client(streamable_http_client(url, http_client=http), mode="legacy") as client:
            got = await client.call_tool("workflow_upload_input", {"filename": "big.png", "content_base64": content})
    if code is None:
        assert not got.is_error, got.content[0].text[:300]
        assert got.structured_content["size_bytes"] == size
    else:
        error = error_of(got)
        assert (error["code"], error["size_bytes"], error["limit"]) == (code, size, tw.MAX_UPLOAD_BYTES)
        assert fake.count("POST", "/upload/image") == 0


# -- #145 second review ------------------------------------------------------------------------


async def run_job(fake: FakeComfyUI, progress: dict, then=None):
    """A workflow run as a job in a store, with its submission answered (then `then()`)."""
    started = asyncio.Event()
    store = JobStore()
    job = store.submit(tw.RUN_KIND, producer(fake, progress, started, then=then))
    await asyncio.wait_for(started.wait(), 5)
    return store, job


async def test_a_cancel_after_the_prompt_succeeded_keeps_its_result():
    """R1: ComfyUI finished it before the cancel. Say so, and keep what it produced."""
    fake = FakeComfyUI(auto="hold")
    progress = {"prompt_id": "p"}
    fake.before_cancel = fake.finish  # it completes just before the cancel reaches ComfyUI
    store, job = await run_job(fake, progress)
    await store.cancel(job.id)
    assert fake.count("POST", "/api/jobs/p/cancel") == 1
    assert job.state.value == "succeeded" and job.cancel_reason == "cancel"
    assert job.result == {
        "prompt_id": "p",
        "status": "success",
        "files": [{"node_id": "4", "filename": "t1__00001_.png", "subfolder": "", "type": "output"}],
    }
    assert progress["stop"] == "already_finished" and progress["comfyui_state"] == "finished"
    assert "stop_detail" not in progress


async def test_a_prompt_that_completes_before_the_interrupt_lands_is_already_finished():
    fake = FakeComfyUI(auto="hold")
    fake.finish_on_cancel = True  # the interrupt was sent, but the last node finished first
    progress = {"prompt_id": "p"}
    store, job = await run_job(fake, progress, then=lambda: fake.start("p"))
    await store.cancel(job.id)
    assert job.state.value == "succeeded" and progress["stop"] == "already_finished"


async def test_a_cancel_after_the_prompt_failed_reports_its_failure():
    fake = FakeComfyUI(auto="hold")
    progress = {"prompt_id": "p"}
    fake.before_cancel = lambda p: fake.finish(p, "error", [["execution_error", RUNTIME_ERROR]], outputs={})
    store, job = await run_job(fake, progress)
    await store.cancel(job.id)
    assert job.state.value == "failed" and job.error["code"] == "workflow_execution_failed"
    assert progress["stop"] == "already_finished"


async def test_job_cancel_of_a_finished_prompt_says_so_and_outputs_still_work():
    fake = FakeComfyUI(auto="hold")
    server, _ = serve(fake)
    async with Client(server, mode="legacy") as client:
        started = (await client.call_tool("workflow_run", {"workflow": t1()})).structured_content
        fake.before_cancel = fake.finish  # it completes just before the cancel reaches ComfyUI
        cancelled = (await client.call_tool("job_cancel", {"job_id": started["job_id"]})).structured_content
        outputs = await client.call_tool("workflow_outputs", {"job_id": started["job_id"]})
    assert cancelled["state"] == "succeeded" and cancelled["result"]["status"] == "success"
    assert cancelled["progress"]["stop"] == "already_finished"
    assert cancelled["progress"]["comfyui_state"] == "finished"
    assert [f["filename"] for f in outputs.structured_content["files"]] == ["t1__00001_.png"]


async def test_a_reset_connection_during_the_stop_is_retried():
    """R2: one failed request no longer ends the stop as unconfirmed."""
    fake = FakeComfyUI(auto="hold")
    started, progress = asyncio.Event(), {"prompt_id": "p"}
    reset = lambda: (fake.start("p"), fake.fail_once.add("/api/jobs/p/cancel"))  # noqa: E731
    await assert_producer_honours_cancel(producer(fake, progress, started, then=reset), started=started)
    assert progress["stop"] == "confirmed" and "stop_detail" not in progress
    assert fake.running == [] and fake.history["p"]["status"]["messages"][0][0] == "execution_interrupted"


async def test_a_non_retryable_error_ends_the_stop_at_once():
    fake = FakeComfyUI(auto="hold")
    started, progress = asyncio.Event(), {"prompt_id": "p"}
    refuse = lambda: fake.fail_status.update({"/api/jobs/p/cancel": 400})  # noqa: E731
    await assert_producer_honours_cancel(producer(fake, progress, started, then=refuse), started=started)
    assert progress["stop"] == "unconfirmed" and "HTTP 400" in progress["stop_detail"]
    assert fake.count("POST", "/api/jobs/p/cancel") == 1  # not retried: it would fail the same way


async def test_a_5xx_during_the_stop_is_retried():
    fake = FakeComfyUI(auto="hold")
    started, progress = asyncio.Event(), {"prompt_id": "p"}
    flaky = lambda: fake.fail_status.update({"/api/jobs/p/cancel": 503})  # noqa: E731
    store = JobStore()
    job = store.submit(tw.RUN_KIND, producer(fake, progress, started, then=flaky))
    await asyncio.wait_for(started.wait(), 5)
    asyncio.get_running_loop().call_later(0.5, fake.fail_status.clear)  # ComfyUI recovers inside the budget
    await store.cancel(job.id)
    assert progress["stop"] == "confirmed" and fake.count("POST", "/api/jobs/p/cancel") > 1


@pytest.mark.usefixtures("quick_stop")
async def test_a_submission_answering_during_the_first_cancel_is_cancelled_by_its_own_id():
    """Note: the answer arrives while the first cancel (by our id) is in flight, carrying an id ComfyUI minted."""
    fake = FakeComfyUI(auto="hold")
    fake.mint_ids = True
    fake.delays["/prompt"] = 0.6  # past what the unwind waits for it (0.8s budget less the 0.3s reserve)...
    fake.delays["/api/jobs/p-ours/cancel"] = 0.2  # ...and answered while this is in flight
    progress = {"prompt_id": "p-ours"}
    await assert_producer_honours_cancel(lambda: tw.run_prompt(fake.client(), t1(), progress))
    assert progress["prompt_id"] == "minted-1"
    assert fake.count("POST", "/api/jobs/minted-1/cancel") >= 1
    assert fake.pending == [] and progress["stop"] == "confirmed"


@pytest.mark.usefixtures("quick_stop")
async def test_a_late_confirmation_replaces_the_timeout_detail():
    """Note: the stop outlives the budget (unconfirmed, with why), then confirms: the why goes with it."""
    fake = FakeComfyUI(auto="hold")
    started, progress = asyncio.Event(), {"prompt_id": "p"}
    slow_checks = lambda: (fake.start("p"), fake.delays.update({"/api/jobs/p": 1.0}))  # noqa: E731
    await assert_producer_honours_cancel(producer(fake, progress, started, then=slow_checks), started=started)
    assert progress["stop"] == "unconfirmed" and "within 0.8s" in progress["stop_detail"]
    await asyncio.sleep(0.6)  # the check that was in flight answers: cancelled
    assert progress["stop"] == "confirmed" and "stop_detail" not in progress


async def test_vanished_counts_consecutive_absences_only():
    fake = FakeComfyUI(auto="hold")
    fake.pending.append([1, "p", {}, {}, []])
    fake.absent_polls = {1, 2, 4, 5, 7, 8}  # never three in a row
    task = asyncio.ensure_future(tw._follow(fake.client(), {"prompt_id": "p"}))
    await asyncio.sleep(0.3)
    assert not task.done()
    fake.finish("p")
    assert (await asyncio.wait_for(task, 5))["status"] == "success"


async def test_a_json_404_that_is_not_comfyuis_is_an_error_not_a_missing_job():
    """R4: a proxy's JSON 404 must not read as 'no such job', which would end in workflow_vanished."""

    def proxy(_request):
        return httpx2.Response(404, json={"error": "no route to upstream"})

    client = ComfyUIClient("http://comfyui.test:8188", transport=httpx2.MockTransport(proxy))
    with pytest.raises(tw.ComfyUIError) as info:
        await client.job("p")
    assert (info.value.code, info.value.detail["status"]) == ("comfyui_http_error", 404)
    ok = ComfyUIClient(
        "http://comfyui.test:8188",
        transport=httpx2.MockTransport(lambda _r: httpx2.Response(404, json={"error": "Job not found"})),
    )
    assert await ok.job("p") is None
    with pytest.raises(tw.ComfyUIError):
        await tw._follow(client, {"prompt_id": "p"})


async def test_a_shared_read_lives_from_when_it_completed(monkeypatch):
    monkeypatch.setattr(tw, "OBJECT_INFO_TTL_SECONDS", 0.2)
    fake = FakeComfyUI()
    fake.delays["/object_info"] = 0.3  # slower than the TTL
    server, _ = serve(fake)
    async with Client(server, mode="legacy") as client:
        await client.call_tool("workflow_validate", {"workflow": t1()})
        await client.call_tool("workflow_validate", {"workflow": t1()})
    assert fake.count("GET", "/object_info") == 1


async def test_a_cancelled_shared_read_is_not_kept():
    future = asyncio.get_running_loop().create_future()
    read = tw._Read(future)
    future.cancel()
    await asyncio.sleep(0)
    assert read.fresh(10) is False  # and no CancelledError from .exception()


async def test_uploads_decode_and_send_one_at_a_time():
    fake = FakeComfyUI()
    fake.delays["upload"] = 0.1
    server, _ = serve(fake)
    async with Client(server, mode="legacy") as client:
        await asyncio.gather(
            *(
                client.call_tool(
                    "workflow_upload_input",
                    {"filename": f"f{i}.png", "content_base64": base64.b64encode(PNG + bytes([i])).decode()},
                )
                for i in range(4)
            )
        )
    assert fake.count("POST", "/upload/image") == 4 and fake.max_uploading == tw.UPLOAD_CONCURRENCY == 1


@pytest.mark.parametrize(("profiles", "limited"), [(("read",), True), (("read", "run"), False)])
async def test_the_larger_body_limit_comes_with_the_run_profile_only(profiles, limited):
    from comfyrelay.server import http_app

    s = settings(profiles=profiles)
    server, _ = build_server(s, comfyui=FakeComfyUI().client())
    app = http_app(server, s)
    body = b"{" + b" " * (5 * 1024 * 1024) + b"}"  # 5 MiB: over the SDK's 4 MiB, under the run profile's limit
    starlette = app.app  # inside TokenAuth; its lifespan starts the MCP session manager
    async with (
        starlette.router.lifespan_context(starlette),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1") as http,
    ):
        response = await http.post(
            "/mcp",
            content=body,
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
    assert (response.status_code == 413) is limited


@pytest.mark.usefixtures("quick_stop")
async def test_an_unconfirmed_stop_catches_up_with_how_the_prompt_ended():
    """The budget ran out with the prompt still running; it then completed. job_status must end up saying so."""
    fake = FakeComfyUI(auto="hold")
    fake.stubborn = True
    started, progress = asyncio.Event(), {"prompt_id": "p"}
    await assert_producer_honours_cancel(
        producer(fake, progress, started, then=lambda: fake.start("p")), started=started
    )
    assert progress["stop"] == "unconfirmed"
    fake.finish("p")  # the last node finished
    await asyncio.sleep(tw.SETTLE_SECONDS * 2 + 0.2)
    assert (progress["stop"], progress["comfyui_state"]) == ("already_finished", "finished")
    assert "stop_detail" not in progress


# -- re-attach after a restart (#146) ------------------------------------------------------------------------------


async def run_and_restart(fake: FakeComfyUI, *, wait: bool = False) -> tuple[dict, dict | None, object]:
    """workflow_run on one relay, which then stops the way SIGTERM stops it (its prompt is left running on ComfyUI),
    and a fresh relay on the same ComfyUI. Returns the run as started, the first relay's own final view of the job
    (with `wait`), and the restarted server."""
    server, relay = serve(fake)
    held = None
    async with Client(server, mode="legacy") as client:
        started = (await client.call_tool("workflow_run", {"workflow": t1()})).structured_content
        if wait:
            held = (
                await client.call_tool("job_status", {"job_id": started["job_id"], "timeout_seconds": 5})
            ).structured_content
    await relay.jobs.shutdown()
    restarted, _ = serve(fake)
    return started, held, restarted


async def test_a_runs_job_id_is_its_prompt_id_and_other_ids_cannot_collide():
    fake = FakeComfyUI()
    server, relay = serve(fake)
    async with Client(server, mode="legacy") as client:
        started = (await client.call_tool("workflow_run", {"workflow": t1()})).structured_content
    other = relay.jobs.submit("test.other", lambda: asyncio.sleep(0))
    assert started["job_id"] == started["prompt_id"] == str(uuid.UUID(started["job_id"]))  # canonical, hyphenated
    assert len(other.id) == 32 and "-" not in other.id  # what the store mints never looks like a prompt id
    await relay.jobs.shutdown()


async def test_a_held_run_takes_the_in_memory_path_and_asks_comfyui_nothing():
    fake = FakeComfyUI()
    server, _ = serve(fake)
    async with Client(server, mode="legacy") as client:
        job_id = await finished_job(client)
        polls = fake.count("GET", "/api/jobs/")
        view = (await client.call_tool("job_status", {"job_id": job_id})).structured_content
    assert fake.count("GET", "/api/jobs/") == polls
    assert (view["source"], view["state"]) == ("relay", "succeeded")
    assert view["summary"].startswith("workflow run: 4 nodes")


async def test_a_restarted_relay_follows_a_run_on_comfyui_by_its_job_id():
    fake = FakeComfyUI(auto="hold")
    fake.pending.append([0, "someone-elses", {}, {}, []])
    started, _, restarted = await run_and_restart(fake)
    prompt_id = started["prompt_id"]
    async with Client(restarted, mode="legacy") as client:
        queued = (await client.call_tool("job_status", {"job_id": started["job_id"]})).structured_content
        fake.start(prompt_id)
        running = (await client.call_tool("job_status", {"job_id": started["job_id"]})).structured_content
        asyncio.get_running_loop().call_later(0.1, fake.finish, prompt_id)
        done = (
            await client.call_tool("job_status", {"job_id": started["job_id"], "timeout_seconds": 5})
        ).structured_content
    assert (queued["source"], queued["job_id"], queued["kind"]) == ("comfyui", prompt_id, "workflow.run")
    assert (queued["state"], queued["finished"]) == ("running", False)  # live, as a held run reports it
    assert queued["progress"] == {"prompt_id": prompt_id, "comfyui_state": "queued", "queue_position": 1}
    assert queued["created_at"] == 1_790_000_000.001
    assert running["progress"] == {"prompt_id": prompt_id, "comfyui_state": "running"}
    assert (done["state"], done["finished"], done["source"]) == ("succeeded", True, "comfyui")
    assert done["result"] == {
        "prompt_id": prompt_id,
        "status": "success",
        "files": [{"node_id": "4", "filename": "t1__00001_.png", "subfolder": "", "type": "output"}],
    }
    assert (done["started_at"], done["finished_at"]) == (1_790_000_001.0, 1_790_000_002.0)


@pytest.mark.parametrize("auto", ["success", "error"])
async def test_a_reattached_run_ends_as_the_held_one_did(auto):
    """The same finish() maps both: what a restarted relay reports is what the first one did."""
    fake = FakeComfyUI(auto=auto)
    started, held, restarted = await run_and_restart(fake, wait=True)
    async with Client(restarted, mode="legacy") as client:
        found = (await client.call_tool("job_status", {"job_id": started["job_id"]})).structured_content
    assert held["source"] == "relay" and found["source"] == "comfyui"
    assert (found["state"], found["result"], found["error"]) == (held["state"], held["result"], held["error"])
    assert found["state"] == ("succeeded" if auto == "success" else "failed")


async def test_a_reattached_run_that_was_interrupted_is_cancelled():
    fake = FakeComfyUI(auto="hold")
    started, _, restarted = await run_and_restart(fake)
    fake.start(started["prompt_id"])
    fake.finish(started["prompt_id"], "error", [["execution_interrupted", {"node_id": "3", "node_type": "X"}]])
    async with Client(restarted, mode="legacy") as client:
        found = (await client.call_tool("job_status", {"job_id": started["job_id"]})).structured_content
    assert (found["state"], found["finished"], found["result"], found["error"]) == ("cancelled", True, None, None)


async def test_outputs_after_a_restart_are_listed_and_fetched_from_comfyui():
    fake = FakeComfyUI()
    started, _, restarted = await run_and_restart(fake, wait=True)
    async with Client(restarted, mode="legacy") as client:
        listed = (await client.call_tool("workflow_outputs", {"job_id": started["job_id"]})).structured_content
        fetched = await client.call_tool("workflow_outputs", {"job_id": started["job_id"], "fetch": "t1__00001_.png"})
    assert (listed["source"], listed["job_state"]) == ("comfyui", "succeeded")
    assert listed["prompt_id"] == started["prompt_id"]
    assert [(f["filename"], f["size_bytes"]) for f in listed["files"]] == [("t1__00001_.png", len(PNG))]
    assert fetched.content[1].type == "image" and base64.b64decode(fetched.content[1].data) == PNG


async def test_outputs_of_an_unfinished_reattached_run_says_to_wait():
    fake = FakeComfyUI(auto="hold")
    started, _, restarted = await run_and_restart(fake)
    async with Client(restarted, mode="legacy") as client:
        error = error_of(await client.call_tool("workflow_outputs", {"job_id": started["job_id"]}))
    assert (error["code"], error["retryable"], error["state"]) == ("job_not_finished", True, "running")


@pytest.mark.parametrize(
    ("tool", "args"),
    [("job_status", {}), ("job_status", {"timeout_seconds": 1}), ("workflow_outputs", {}), ("job_cancel", {})],
)
async def test_an_id_neither_held_nor_on_comfyui_is_unknown_job(tool, args):
    fake = FakeComfyUI()
    server, _ = serve(fake)
    missing = str(uuid.uuid4())
    async with Client(server, mode="legacy") as client:
        error = error_of(await client.call_tool(tool, {"job_id": missing, **args}))
    assert (error["code"], error["retryable"], error["job_id"]) == ("unknown_job", False, missing)
    assert "ComfyUI has no prompt by that id" in error["message"]
    assert fake.count("GET", f"/api/jobs/{missing}") == 1


@pytest.mark.parametrize("extra_data", [{}, {"client_id": "a-browser-tab"}, {"client_id": "comfyrelay:another"}])
@pytest.mark.parametrize("running", [False, True])
async def test_cancel_of_another_clients_prompt_is_refused_and_touches_nothing(extra_data, running):
    """No client_id, the ComfyUI frontend's, or a relay with another instance id: not provably this relay's."""
    fake = FakeComfyUI(auto="hold")
    theirs = str(uuid.uuid4())
    fake.pending.append([7, theirs, {}, extra_data, []])
    if running:
        fake.start(theirs)
    server, _ = serve(fake)
    async with Client(server, mode="legacy") as client:
        error = error_of(await client.call_tool("job_cancel", {"job_id": theirs}))
        status = (await client.call_tool("job_status", {"job_id": theirs})).structured_content
    assert (error["code"], error["retryable"]) == ("job_not_owned", False)
    assert error["comfyui_status"] == ("in_progress" if running else "pending")
    assert "a-browser-tab" not in error["message"]  # another client's id is not echoed
    assert fake.count("POST", "/api/jobs/") == 0 and fake.posted("/queue") == [] and fake.posted("/interrupt") == []
    assert theirs in [i[1] for i in (*fake.pending, *fake.running)]
    assert status["source"] == "comfyui"  # still readable by id


async def test_cancel_after_a_restart_with_a_new_instance_id_is_refused():
    """A relay whose COMFYUI_MCP_INSTANCE_ID changed (it defaults to the hostname) cannot prove its old prompts."""
    fake = FakeComfyUI(auto="hold")
    server, relay = build_server(settings(instance_id="before"), comfyui=fake.client())
    async with Client(server, mode="legacy") as client:
        started = (await client.call_tool("workflow_run", {"workflow": t1()})).structured_content
    await relay.jobs.shutdown()
    async with Client(serve(fake)[0], mode="legacy") as client:
        error = error_of(await client.call_tool("job_cancel", {"job_id": started["job_id"]}))
    assert error["code"] == "job_not_owned" and "comfyrelay:test-instance" in error["message"]
    assert fake.count("POST", "/api/jobs/") == 0


async def test_cancel_after_a_restart_stops_a_queued_run_this_relay_submitted():
    fake = FakeComfyUI(auto="hold")
    started, _, restarted = await run_and_restart(fake)
    async with Client(restarted, mode="legacy") as client:
        cancelled = (await client.call_tool("job_cancel", {"job_id": started["job_id"]})).structured_content
    assert (cancelled["state"], cancelled["finished"], cancelled["source"]) == ("cancelled", True, "comfyui")
    assert cancelled["progress"]["stop"] == "confirmed"
    assert fake.pending == [] and fake.count("POST", f"/api/jobs/{started['prompt_id']}/cancel") == 1
    assert fake.posted("/interrupt") == []


async def test_cancel_after_a_restart_stops_a_running_run_this_relay_submitted():
    fake = FakeComfyUI(auto="hold")
    started, _, restarted = await run_and_restart(fake)
    fake.start(started["prompt_id"])
    async with Client(restarted, mode="legacy") as client:
        cancelled = (await client.call_tool("job_cancel", {"job_id": started["job_id"]})).structured_content
    assert (cancelled["state"], cancelled["result"], cancelled["error"]) == ("cancelled", None, None)
    assert (cancelled["progress"]["stop"], cancelled["progress"]["comfyui_state"]) == ("confirmed", "finished")
    assert fake.running == [] and fake.posted("/interrupt") == []


async def test_cancel_after_a_restart_of_a_run_that_got_there_first_reports_how_it_ended():
    fake = FakeComfyUI(auto="hold")
    started, _, restarted = await run_and_restart(fake)
    fake.start(started["prompt_id"])
    fake.finish_on_cancel = True
    async with Client(restarted, mode="legacy") as client:
        found = (await client.call_tool("job_cancel", {"job_id": started["job_id"]})).structured_content
    assert (found["state"], found["progress"]["stop"]) == ("succeeded", "already_finished")
    assert found["result"]["files"][0]["filename"] == "t1__00001_.png"


async def test_cancel_of_a_finished_reattached_run_reports_it_and_sends_nothing():
    fake = FakeComfyUI()
    started, held, restarted = await run_and_restart(fake, wait=True)
    async with Client(restarted, mode="legacy") as client:
        found = (await client.call_tool("job_cancel", {"job_id": started["job_id"]})).structured_content
    assert (found["state"], found["source"], found["result"]) == ("succeeded", "comfyui", held["result"])
    assert fake.count("POST", "/api/jobs/") == 0
