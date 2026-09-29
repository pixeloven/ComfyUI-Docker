"""The introspection tools against a real, booted ComfyUI. Skipped unless
COMFYRELAY_LIVE_COMFYUI_URL names one, for example a core-cpu started by
tests/agent-tasks/up.sh:

    cd services
    COMFYRELAY_LIVE_COMFYUI_URL=http://127.0.0.1:8188 \
      uv run --locked pytest -q comfyrelay/tests/test_relay_introspection_live.py

It needs no model. It uploads a small image into that ComfyUI's input
directory and queues two tiny image graphs, so point it at a scratch instance.
"""

from __future__ import annotations

import asyncio
import os
import struct
import uuid
import zlib
from typing import Any

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


def png(width: int = 32, height: int = 24) -> bytes:
    row = b"\x00" + bytes(int(255 * x / (width - 1)) for x in range(width) for _ in range(3))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


async def upload(name: str) -> None:
    async with httpx2.AsyncClient(base_url=URL, timeout=30) as http:
        r = await http.post("/upload/image", files={"image": (name, png(), "image/png")}, data={"overwrite": "true"})
        r.raise_for_status()


async def call(tool: str, args: dict) -> dict:
    server, _ = build_server(settings(comfyui_url=URL), comfyui=ComfyUIClient(URL))
    async with Client(server, mode="legacy") as client:
        result = await client.call_tool(tool, args)
    assert not result.is_error, result.content[0].text
    return result.structured_content


def fill(inputs: list[dict], image: list) -> dict[str, Any]:
    """Values for a node's required inputs, taken only from node_describe's output: defaults for widgets, the
    first option of a (dynamic) combo, and `image` for any IMAGE or match-type socket. Keys are the names
    node_describe gives, so a wrong qualified name fails ComfyUI's validation."""
    out: dict[str, Any] = {}
    for spec in inputs:
        if not spec["required"]:
            continue
        kind = spec["type"]
        if kind in ("IMAGE", "COMFY_MATCHTYPE_V3"):
            out[spec["name"]] = image
        elif kind == "COMFY_AUTOGROW_V3":
            grow = spec["autogrow"]
            for name in grow["names"][: max(grow["min"], 2)]:
                out[name] = image
        elif kind == "COMFY_DYNAMICCOMBO_V3":
            option = spec["options"][0]
            out[spec["name"]] = option["value"]
            out.update(fill(option["inputs"], image))
        elif "default" in spec:
            out[spec["name"]] = spec["default"]
        elif kind == "COMBO":
            out[spec["name"]] = spec["options"][0]
        else:
            raise AssertionError(f"no value for {spec}")
    return out


async def queue_and_wait(graph: dict) -> dict:
    async with httpx2.AsyncClient(base_url=URL, timeout=30) as http:
        r = await http.post("/prompt", json={"prompt": graph})
        body = r.json()
        assert r.status_code == 200 and not body.get("node_errors"), body
        prompt_id = body["prompt_id"]
        for _ in range(120):
            entry = (await http.get(f"/history/{prompt_id}")).json().get(prompt_id)
            if entry and entry.get("status", {}).get("completed") is not None:
                return entry
            await asyncio.sleep(0.5)
    raise AssertionError(f"{prompt_id} did not finish")


@pytest.mark.parametrize("class_type", ["ResizeImageMaskNode", "BatchImagesNode"])
async def test_a_graph_built_from_node_describe_passes_prompt_validation(class_type):
    name = f"relay-live-{uuid.uuid4().hex[:8]}.png"
    await upload(name)
    spec = await call("node_describe", {"class_type": class_type})
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": name}},
        "2": {"class_type": class_type, "inputs": fill(spec["inputs"], ["1", 0])},
        "3": {"class_type": "PreviewImage", "inputs": {"images": ["2", 0]}},
    }
    assert any("." in key for key in graph["2"]["inputs"]), graph  # dotted names are really in play
    entry = await queue_and_wait(graph)
    assert entry["status"]["status_str"] == "success", entry["status"]


async def test_node_describe_finds_the_help_page_where_comfyui_serves_it():
    got = await call("node_describe", {"class_type": "KSampler"})
    assert got["help_path"] == "/docs/KSampler/en.md"
    assert got["help"].strip()


async def test_a_template_input_is_reported_exactly_while_the_input_directory_lacks_it():
    found = await call("template_search", {"query": "color adjustment", "limit": 1})
    (hit,) = found["results"]
    got = await call("template_get", {"name": hit["name"], "include_workflow": False})
    async with httpx2.AsyncClient(base_url=URL, timeout=30) as http:
        workflow = (await http.get(f"/templates/{hit['name']}.json")).json()
        present = set((await http.get("/object_info/LoadImage")).json()["LoadImage"]["input"]["required"]["image"][0])
    nodes = workflow["nodes"] + [n for s in workflow.get("definitions", {}).get("subgraphs", []) for n in s["nodes"]]
    wanted = {n["widgets_values"][0] for n in nodes if n["type"] == "LoadImage" and n.get("mode") not in (2, 4)}
    assert wanted, "the template has no LoadImage to check"
    assert {m["file"] for m in got["runnability"]["missing_inputs"]} == wanted - present
    assert got["runnability"]["runnable"] is (not (wanted - present))
    for name in wanted - present:
        await upload(name)
    again = await call("template_get", {"name": hit["name"], "include_workflow": False})
    assert again["runnability"]["missing_inputs"] == []
    assert again["runnability"]["runnable"] is True
