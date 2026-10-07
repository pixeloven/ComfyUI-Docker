"""tools/list stays small (#169): at about 95 KB as an agent's client printed it, agents' tooling wrote it to a file
instead of reading it, which cost a call. It is measured as the server sends it, compact JSON."""

from __future__ import annotations

import json

import pytest
from comfyrelay.server import build_server
from mcp import Client
from relay_helpers import comfyui_answering, settings

pytestmark = pytest.mark.anyio


# Bytes of the compact tools/list result. Each ceiling is about a third over its size when it was set (read 8.7 KB,
# read,run 14.7 KB), so a new tool or argument fits, but schema bloat or a run of long descriptions does not.
@pytest.mark.parametrize(
    ("overrides", "ceiling"),
    [
        ({"profiles": ("read",)}, 12_000),
        ({"profiles": ("read", "run")}, 20_000),
        ({"profiles": ("read", "run"), "convert": True}, 20_000),  # as the mcp-convert image serves it
    ],
)
async def test_tools_list_stays_under_its_ceiling(overrides, ceiling):
    server, _ = build_server(settings(**overrides), comfyui=comfyui_answering())
    async with Client(server, mode="legacy") as client:
        tools = (await client.list_tools()).tools
    listed = [t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in tools]
    size = len(json.dumps({"tools": listed}, separators=(",", ":"), ensure_ascii=False).encode())
    by_tool = sorted(((len(json.dumps(t, separators=(",", ":"))), t["name"]) for t in listed), reverse=True)
    assert size <= ceiling, f"tools/list is {size} bytes, over {ceiling}; largest: {by_tool[:3]}"
    assert not any("outputSchema" in t for t in listed)
