"""The workflow tools against a real, booted ComfyUI. Skipped unless
COMFYRELAY_LIVE_COMFYUI_URL names one, for example a core-cpu started by
tests/agent-tasks/up.sh or tests/relay/run.sh's boot:

    cd services
    COMFYRELAY_LIVE_COMFYUI_URL=http://127.0.0.1:8188 \
      uv run --locked pytest -q comfyrelay/tests/test_relay_workflow_live.py

It needs no model: every graph uses built-in image nodes. It writes into that
ComfyUI's input and output directories, so point it at a scratch instance.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import random
import struct
import zlib

import httpx2
import pytest
from comfyrelay import tools_workflow as tw
from comfyrelay.comfyui import ComfyUIClient
from comfyrelay.jobs import JobStore
from comfyrelay.server import build_server
from mcp import Client
from relay_helpers import TOKEN, free_port, settings

URL = os.environ.get("COMFYRELAY_LIVE_COMFYUI_URL", "")
pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not URL, reason="COMFYRELAY_LIVE_COMFYUI_URL is not set"),
]


def gradient_png(width: int = 64, height: int = 48) -> bytes:
    """Black on the left to white on the right, the same shape as the harness's input."""
    row = b"\x00" + bytes(int(255 * x / (width - 1)) for x in range(width) for _ in range(3))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def slow_graph(nodes: int = 200, size: int = 1024) -> dict:
    """A chain of blurs over a large image: about half a second per node on a CPU, and interruptible
    between nodes. A random colour keeps ComfyUI's cache from answering it instantly."""
    graph = {
        "1": {
            "class_type": "EmptyImage",
            "inputs": {"width": size, "height": size, "batch_size": 1, "color": random.randrange(1 << 24)},
        }
    }
    previous = "1"
    for i in range(nodes):
        node = str(10 + i)
        graph[node] = {"class_type": "ImageBlur", "inputs": {"image": [previous, 0], "blur_radius": 31, "sigma": 10.0}}
        previous = node
    graph["9"] = {"class_type": "PreviewImage", "inputs": {"images": [previous, 0]}}
    return graph


async def comfyui_state(prompt_id: str) -> tuple[str, dict | None]:
    """Where ComfyUI itself has the prompt, asked directly rather than through the relay."""
    async with httpx2.AsyncClient(base_url=URL, timeout=10) as http:
        queue = (await http.get("/queue")).json()
        history = (await http.get(f"/history/{prompt_id}")).json().get(prompt_id)
    if any(item[1] == prompt_id for item in queue["queue_running"]):
        return "running", history
    if any(item[1] == prompt_id for item in queue["queue_pending"]):
        return "pending", history
    return "absent", history


@pytest.fixture
async def client():
    server, _ = build_server(settings(comfyui_url=URL), comfyui=ComfyUIClient(URL))
    async with Client(server, mode="legacy") as c:
        yield c


async def test_upload_run_and_fetch_the_outputs(client):
    up = await client.call_tool(
        "workflow_upload_input",
        {"filename": "relay-live-input.png", "content_base64": base64.b64encode(gradient_png()).decode()},
    )
    assert not up.is_error, up.content[0].text
    name = up.structured_content["name"]
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": name}},
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
        "4": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "relay_live_"}},
    }
    checked = await client.call_tool("workflow_validate", {"workflow": graph})
    assert checked.structured_content["runnable"] is True, checked.structured_content

    started = await client.call_tool("workflow_run", {"workflow": graph})
    assert not started.is_error, started.content[0].text
    job_id = started.structured_content["job_id"]
    done = await client.call_tool("job_status", {"job_id": job_id, "timeout_seconds": 60})
    assert done.structured_content["state"] == "succeeded", done.structured_content
    [saved] = done.structured_content["result"]["files"]
    assert saved["filename"].startswith("relay_live_")

    listed = await client.call_tool("workflow_outputs", {"job_id": job_id, "fetch": saved["filename"]})
    assert not listed.is_error, listed.content[0].text
    [file] = listed.structured_content["files"]
    assert file["size_bytes"] > 0 and file["mime_type"] == "image/png"
    image = listed.content[1]
    assert image.type == "image" and image.mime_type == "image/png"
    png = base64.b64decode(image.data)
    assert png.startswith(b"\x89PNG") and struct.unpack(">II", png[16:24]) == (256, 256)


async def test_comfyuis_rejection_maps_into_workflow_rejected(client):
    """The contract with /prompt: the relay no longer type-checks, so a MASK wired into SaveImage's IMAGE input
    passes workflow_validate, and ComfyUI's own per-node error comes back through workflow_run."""
    graph = {
        "1": {"class_type": "EmptyImage", "inputs": {"width": 64, "height": 64, "batch_size": 1, "color": 0}},
        "2": {"class_type": "ImageToMask", "inputs": {"image": ["1", 0], "channel": "red"}},
        "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": "never_"}},
    }
    checked = (await client.call_tool("workflow_validate", {"workflow": graph})).structured_content
    assert checked["valid"] and checked["runnable"]
    refused = await client.call_tool("workflow_run", {"workflow": graph})
    assert refused.is_error
    text = refused.content[0].text
    error = json.loads(text[text.index("{") :])["error"]
    assert error["code"] == "workflow_rejected"
    assert error["comfyui_error"]["type"] == "prompt_outputs_failed_validation"
    [problem] = error["errors"]
    assert (problem["type"], problem["node_id"], problem["class_type"], problem["input"]) == (
        "return_type_mismatch",
        "3",
        "SaveImage",
        "images",
    )
    assert (problem["expected"], problem["got"]) == ("IMAGE", "MASK")
    assert problem["details"] == "images, received_type(MASK) mismatch input_type(IMAGE)"


async def test_a_custom_combo_value_passes_and_runs(client):
    """CustomCombo's options list is empty in /object_info, and any value is valid: a copied COMBO check refused
    it, ComfyUI accepts it."""
    graph = {
        "1": {"class_type": "CustomCombo", "inputs": {"choice": f"my own option {random.randrange(1 << 24)}"}},
        "2": {"class_type": "PreviewAny", "inputs": {"source": ["1", 0]}},
    }
    checked = (await client.call_tool("workflow_validate", {"workflow": graph})).structured_content
    assert checked["valid"] and checked["runnable"] and checked["errors"] == []
    started = await client.call_tool("workflow_run", {"workflow": graph})
    assert not started.is_error, started.content[0].text
    done = await client.call_tool("job_status", {"job_id": started.structured_content["job_id"], "timeout_seconds": 60})
    assert done.structured_content["state"] == "succeeded", done.structured_content


async def test_an_execution_error_names_the_node(client):
    graph = {
        "1": {"class_type": "EmptyImage", "inputs": {"width": 64, "height": 64, "batch_size": 1, "color": 0}},
        "2": {"class_type": "ImageToMask", "inputs": {"image": ["1", 0], "channel": "alpha"}},  # RGB has no alpha
        "3": {"class_type": "MaskPreview", "inputs": {"mask": ["2", 0]}},
    }
    started = await client.call_tool("workflow_run", {"workflow": graph})
    done = await client.call_tool("job_status", {"job_id": started.structured_content["job_id"], "timeout_seconds": 60})
    assert done.structured_content["state"] == "failed"
    error = done.structured_content["error"]
    assert (error["code"], error["node_id"], error["node_type"]) == ("workflow_execution_failed", "2", "ImageToMask")


async def wait_for(predicate, timeout: float = 30.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not await predicate():
        assert asyncio.get_running_loop().time() < deadline, "timed out"
        await asyncio.sleep(0.25)


async def test_cancelling_stops_the_prompt_on_comfyui_running_and_queued(client):
    """Two slow prompts: the first runs, the second waits behind it. Cancel the second, then the first, and
    confirm with ComfyUI directly that the queued one never ran and the running one stopped."""
    first = (await client.call_tool("workflow_run", {"workflow": slow_graph()})).structured_content
    second = (await client.call_tool("workflow_run", {"workflow": slow_graph()})).structured_content

    async def first_running():
        return (await comfyui_state(first["prompt_id"]))[0] == "running"

    await wait_for(first_running)
    status = await client.call_tool("job_status", {"job_id": second["job_id"]})
    assert status.structured_content["progress"]["comfyui_state"] == "queued"
    assert status.structured_content["progress"]["queue_position"] == 0

    loop = asyncio.get_running_loop()
    t0 = loop.time()
    cancelled = await client.call_tool("job_cancel", {"job_id": second["job_id"]})
    assert cancelled.structured_content["state"] == "cancelled"
    assert cancelled.structured_content["progress"]["stop"] == "confirmed"
    assert loop.time() - t0 < 3.0
    assert await comfyui_state(second["prompt_id"]) == ("absent", None)  # dequeued, never ran

    t0 = loop.time()
    cancelled = await client.call_tool("job_cancel", {"job_id": first["job_id"]})
    assert cancelled.structured_content["state"] == "cancelled"
    assert cancelled.structured_content["progress"]["stop"] == "confirmed"  # ComfyUI said so, within the budget
    assert loop.time() - t0 < 3.0

    async def first_stopped():
        return (await comfyui_state(first["prompt_id"]))[1] is not None

    await wait_for(first_stopped, timeout=10)  # interrupted at the next node boundary
    where, entry = await comfyui_state(first["prompt_id"])
    assert where == "absent"
    assert entry["status"]["status_str"] == "error"
    assert "execution_interrupted" in [m[0] for m in entry["status"]["messages"]]
    assert await comfyui_state(second["prompt_id"]) == ("absent", None)


async def comfyui_cancel(prompt_id: str) -> None:
    """Clean-up, straight to ComfyUI, whatever a test left behind."""
    async with httpx2.AsyncClient(base_url=URL, timeout=10) as http:
        await http.post(f"/api/jobs/{prompt_id}/cancel")


async def test_a_double_cancel_still_stops_the_prompt(client):
    """#145 R1, on ComfyUI itself: two job_cancels at once, the second landing during the first's unwind."""
    run = (await client.call_tool("workflow_run", {"workflow": slow_graph()})).structured_content
    try:

        async def running():
            return (await comfyui_state(run["prompt_id"]))[0] == "running"

        await wait_for(running)
        both = await asyncio.gather(
            client.call_tool("job_cancel", {"job_id": run["job_id"]}),
            client.call_tool("job_cancel", {"job_id": run["job_id"]}),
        )
        assert [b.structured_content["state"] for b in both] == ["cancelled", "cancelled"]
        assert both[0].structured_content["progress"]["stop"] == "confirmed"

        async def stopped():
            return (await comfyui_state(run["prompt_id"]))[1] is not None

        await wait_for(stopped, timeout=10)
        where, entry = await comfyui_state(run["prompt_id"])
        assert where == "absent" and "execution_interrupted" in [m[0] for m in entry["status"]["messages"]]
    finally:
        await comfyui_cancel(run["prompt_id"])


async def test_a_cancel_during_submission_never_orphans_the_prompt():
    """#145 R4, on ComfyUI itself: cancel while a large /prompt is still being processed, five times. ComfyUI
    finishes a /prompt whose client hung up; the stop must not arrive before it and miss the prompt."""
    comfyui = ComfyUIClient(URL)
    # About 2 MB, which ComfyUI takes some 30 ms over. (A chain much deeper than 400 fails ComfyUI's recursive
    # validation with RecursionError at v0.37.0.)
    graph = slow_graph(nodes=400, size=512)
    graph["2"] = {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "x" * 1_500_000}}
    outcomes = []
    try:
        for delay in (0.005, 0.015, 0.03):  # the cancel lands at points across the POST
            graph["1"]["inputs"]["color"] = random.randrange(1 << 24)
            progress = {"prompt_id": str(__import__("uuid").uuid4())}
            store = JobStore()
            job = store.submit(tw.RUN_KIND, lambda progress=progress: tw.run_prompt(comfyui, graph, progress))
            await asyncio.sleep(delay)
            t0 = asyncio.get_running_loop().time()
            await store.cancel(job.id)
            assert asyncio.get_running_loop().time() - t0 < 3.0
            await asyncio.sleep(2.0)  # long enough for a missed prompt to be queued and start
            where, entry = await comfyui_state(progress["prompt_id"])
            await comfyui_cancel(progress["prompt_id"])
            assert where == "absent", f"prompt {progress['prompt_id']} is {where} after its job was cancelled"
            ran = entry is not None and "execution_interrupted" not in [m[0] for m in entry["status"]["messages"]]
            assert not ran, "the prompt ran to an end of its own"
            outcomes.append(progress.get("stop"))
    finally:
        await comfyui.aclose()
    assert all(o in ("confirmed", "unconfirmed") for o in outcomes), outcomes


async def test_a_relay_stopped_by_sigterm_leaves_its_prompt_running():
    """Owner decision on #145: a relay that stops does not stop its runs; a restarted one re-attaches (#146)."""
    import signal
    import subprocess
    import sys
    from pathlib import Path

    from mcp.client.streamable_http import streamable_http_client

    port = free_port()
    env = {
        **os.environ,
        "COMFYUI_MCP_HTTP_TOKEN": TOKEN,
        "COMFYUI_URL": URL,
        "MCP_HOST": "127.0.0.1",
        "MCP_PORT": str(port),
        "COMFYUI_MCP_INSTANCE_ID": "sigterm-test",
    }
    relay = subprocess.Popen(
        [str(Path(sys.executable).parent / "comfyctl"), "relay", "serve"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    prompt_id = None
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"}, timeout=60) as http:
            for _ in range(100):
                try:
                    await http.get(url)
                    break
                except httpx2.TransportError:
                    await asyncio.sleep(0.1)
            async with Client(streamable_http_client(url, http_client=http), mode="legacy") as mcp:
                run = (await mcp.call_tool("workflow_run", {"workflow": slow_graph()})).structured_content
        prompt_id = run["prompt_id"]

        async def running():
            return (await comfyui_state(prompt_id))[0] == "running"

        await wait_for(running)
        relay.send_signal(signal.SIGTERM)
        output, _ = relay.communicate(timeout=10)
        log = output.decode(errors="replace")
        assert relay.returncode is not None
        assert f"prompt {prompt_id} is left running on ComfyUI" in log, log[-2000:]
        await asyncio.sleep(1.5)  # past any stop the relay might have sent
        assert (await comfyui_state(prompt_id))[0] == "running"  # it carries on without the relay
    finally:
        if relay.poll() is None:
            relay.kill()
        if prompt_id is not None:
            await comfyui_cancel(prompt_id)


async def comfyui_job(prompt_id: str) -> dict | None:
    async with httpx2.AsyncClient(base_url=URL, timeout=10) as http:
        response = await http.get(f"/api/jobs/{prompt_id}")
    return response.json() if response.status_code == 200 else None


async def test_a_cancel_racing_a_tiny_prompt_reports_what_comfyui_did(client):
    """#145 second review, R1: cancel a 2-node graph 0.05 to 0.5s after submitting it. Whichever wins, the job
    must agree with ComfyUI: finished there means succeeded here, with its result; cancelled there means
    cancelled here."""
    seen = []
    for delay in (0.05, 0.1, 0.2, 0.3, 0.4, 0.5):
        color = random.randrange(1 << 24)
        graph = {
            "1": {"class_type": "EmptyImage", "inputs": {"width": 8, "height": 8, "batch_size": 1, "color": color}},
            "2": {"class_type": "PreviewImage", "inputs": {"images": ["1", 0]}},
        }
        run = (await client.call_tool("workflow_run", {"workflow": graph})).structured_content
        await asyncio.sleep(delay)
        job = (await client.call_tool("job_cancel", {"job_id": run["job_id"]})).structured_content
        for _ in range(40):  # an unconfirmed stop carries on in the background; let it catch up
            if job["progress"].get("stop") != "unconfirmed":
                break
            await asyncio.sleep(0.25)
            job = (await client.call_tool("job_status", {"job_id": run["job_id"]})).structured_content
        there = await comfyui_job(run["prompt_id"])
        comfy = None if there is None else there["status"]
        seen.append((delay, comfy, job["state"], job["progress"].get("stop")))
        if comfy == "completed":
            assert (job["progress"]["stop"], job["progress"]["comfyui_state"]) == ("already_finished", "finished"), seen
            # Settled within the cancel, the job keeps the result; settled after it, the job had ended cancelled.
            assert job["state"] in ("succeeded", "cancelled"), seen
            if job["state"] == "succeeded":
                assert job["result"]["status"] == "success"
            outputs = await client.call_tool("workflow_outputs", {"job_id": run["job_id"]})
            assert outputs.structured_content["files"], seen
        else:
            assert comfy in (None, "cancelled"), seen
            assert (job["state"], job["progress"]["stop"]) == ("cancelled", "confirmed"), seen
    print("delay, ComfyUI, job, stop:", seen)
