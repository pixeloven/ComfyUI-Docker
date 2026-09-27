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
import os
import random
import struct
import zlib

import httpx2
import pytest
from comfyrelay.comfyui import ComfyUIClient
from comfyrelay.server import build_server
from mcp import Client
from relay_helpers import settings

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


def slow_graph(nodes: int = 200) -> dict:
    """A chain of blurs over a large image: about half a second per node on a CPU, and interruptible
    between nodes. A random colour keeps ComfyUI's cache from answering it instantly."""
    graph = {
        "1": {
            "class_type": "EmptyImage",
            "inputs": {"width": 1024, "height": 1024, "batch_size": 1, "color": random.randrange(1 << 24)},
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


async def test_a_broken_graph_is_refused_with_comfyuis_error_type(client):
    graph = {
        "1": {"class_type": "EmptyImage", "inputs": {"width": 64, "height": 64, "batch_size": 1, "color": 0}},
        "2": {"class_type": "ImageToMask", "inputs": {"image": ["1", 0], "channel": "red"}},
        "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": "never_"}},
    }
    checked = await client.call_tool("workflow_validate", {"workflow": graph})
    [error] = checked.structured_content["errors"]
    assert (error["type"], error["node_id"], error["expected"], error["got"]) == (
        "return_type_mismatch",
        "3",
        "IMAGE",
        "MASK",
    )
    refused = await client.call_tool("workflow_run", {"workflow": graph})
    assert refused.is_error and '"workflow_invalid"' in refused.content[0].text


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
    assert loop.time() - t0 < 3.0
    assert await comfyui_state(second["prompt_id"]) == ("absent", None)  # dequeued, never ran

    t0 = loop.time()
    cancelled = await client.call_tool("job_cancel", {"job_id": first["job_id"]})
    assert cancelled.structured_content["state"] == "cancelled"
    assert loop.time() - t0 < 3.0

    async def first_stopped():
        return (await comfyui_state(first["prompt_id"]))[1] is not None

    await wait_for(first_stopped, timeout=10)  # interrupted at the next node boundary
    where, entry = await comfyui_state(first["prompt_id"])
    assert where == "absent"
    assert entry["status"]["status_str"] == "error"
    assert "execution_interrupted" in [m[0] for m in entry["status"]["messages"]]
    assert await comfyui_state(second["prompt_id"]) == ("absent", None)
