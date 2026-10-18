"""workflow_validate's dry run (#215) against a real, booted ComfyUI. Skipped unless COMFYRELAY_LIVE_COMFYUI_URL
names one. Whether that instance serves the validate-only route decides what is expected: the core image started
with COMFY_ENABLE_VALIDATE_ONLY=true does, and so does any core-cpu with the module mounted, as CI's relay job
mounts it; one without it must be reported as unavailable.

    docker run -d --name dryrun --network host -e COMFY_PORT=8188 -e COMFY_ENABLE_MANAGER=false \
      -e COMFY_ENABLE_VALIDATE_ONLY=true -e CLI_ARGS="--listen 127.0.0.1" ghcr.io/pixeloven/comfyui/core:cpu-<label>
    cd services
    COMFYRELAY_LIVE_COMFYUI_URL=http://127.0.0.1:8188 uv run --locked pytest -q comfyrelay/tests/test_relay_dry_run_live.py

It needs no model: every graph uses built-in image nodes, and none of them runs.
"""

from __future__ import annotations

import os
import random

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


def graph() -> dict:
    """EmptyImage into SaveImage: it would write a file if it ran. A random colour keeps it out of any cache."""
    return {
        "1": {
            "class_type": "EmptyImage",
            "inputs": {"width": 64, "height": 64, "batch_size": 1, "color": random.randrange(1 << 24)},
        },
        "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "dryrun_"}},
    }


async def serves_the_route() -> bool:
    async with httpx2.AsyncClient(base_url=URL, timeout=10) as http:
        response = await http.get("/comfyrelay/validate_only")
    return response.status_code == 200 and response.json().get("validate_only") is True


async def comfyui_seen() -> tuple[int, int]:
    """(prompts queued or running, entries in the history), asked of ComfyUI directly."""
    async with httpx2.AsyncClient(base_url=URL, timeout=10) as http:
        queue = (await http.get("/queue")).json()
        history = (await http.get("/history")).json()
    return len(queue["queue_running"]) + len(queue["queue_pending"]), len(history)


async def validate(workflow: dict) -> dict:
    server, _ = build_server(settings(comfyui_url=URL), comfyui=ComfyUIClient(URL))
    async with Client(server, mode="legacy") as client:
        result = await client.call_tool("workflow_validate", {"workflow": workflow})
    assert not result.is_error, result.content[0].text
    return result.structured_content


async def test_the_dry_run_matches_what_the_instance_serves():
    before = await comfyui_seen()
    got = await validate(graph())
    if await serves_the_route():
        assert got["dry_run"] == {"ran": True, "accepted": True}
    else:
        assert got["dry_run"]["ran"] is False and got["dry_run"]["reason"] == "unavailable"
    assert await comfyui_seen() == before


async def test_comfyuis_own_errors_come_back_and_nothing_is_queued():
    """What workflow_validate's own check passes and /prompt refuses (#145): a MASK into an IMAGE input, a missing
    required input, a COMBO value not in the list, and a number below its minimum."""
    if not await serves_the_route():
        pytest.skip("this ComfyUI doesn't serve the validate-only route")
    before = await comfyui_seen()
    bad = graph()
    bad["1"]["inputs"]["width"] = 0
    bad["3"] = {"class_type": "LoadImage", "inputs": {"image": "no-such-file.png"}}
    bad["4"] = {"class_type": "SaveImage", "inputs": {"images": ["3", 1], "filename_prefix": "dryrun_"}}
    bad["5"] = {
        "class_type": "ImageScale",
        "inputs": {"image": ["1", 0], "upscale_method": "bogus", "width": 32, "crop": "disabled"},
    }
    bad["6"] = {"class_type": "PreviewImage", "inputs": {"images": ["5", 0]}}
    got = await validate(bad)
    assert (got["valid"], got["runnable"]) == (True, True)
    run = got["dry_run"]
    assert run["ran"] is True and run["accepted"] is False
    assert run["error"]["type"] == "prompt_outputs_failed_validation"
    found = {(e["node_id"], e["type"], e.get("input")) for e in run["errors"]}
    assert {
        ("1", "value_smaller_than_min", "width"),
        ("4", "return_type_mismatch", "images"),
        ("5", "value_not_in_list", "upscale_method"),
        ("5", "required_input_missing", "height"),
    } <= found, found
    assert await comfyui_seen() == before
