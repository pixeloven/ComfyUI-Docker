"""tools/list stays small (#169): at about 95 KB as an agent's client printed it, agents' tooling wrote it to a file
instead of reading it, which cost a call. It is measured as the server sends it, compact JSON. What the list leaves
out is only that: each tool keeps its return model, and an input schema loses nothing but its titles."""

from __future__ import annotations

import json

import pytest
from comfyrelay.server import build_server
from mcp import Client
from mcp.server.mcpserver import MCPServer
from relay_helpers import comfyui_answering, settings

pytestmark = pytest.mark.anyio


# Bytes of the compact tools/list result. Each ceiling is about a third over its size when it was set (read 9.0 KB,
# read,run 15.3 KB), so a new tool or argument fits, but schema bloat or a run of long descriptions does not.
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


EVERY_PROFILE = settings(profiles=("read", "run", "manage"))


async def test_every_tool_keeps_a_return_model():
    """The list leaves outputSchema out, but each tool still has one underneath: it is what the SDK checks a result
    against, and what makes it send structuredContent. The SDK's own list_tools, which the override doesn't touch."""
    server, relay = build_server(EVERY_PROFILE, comfyui=comfyui_answering())
    tools = await MCPServer.list_tools(server)
    assert sorted(t.name for t in tools) == sorted(relay.tools)
    for tool in tools:
        assert tool.output_schema is not None, tool.name


def _without_titles(schema: object) -> object:
    """Every "title": <string> pair gone, at any depth. Deliberately blunter than server.untitled, which it checks."""
    if isinstance(schema, list):
        return [_without_titles(s) for s in schema]
    if isinstance(schema, dict):
        return {k: _without_titles(v) for k, v in schema.items() if not (k == "title" and isinstance(v, str))}
    return schema


async def test_the_input_schemas_lose_only_their_titles():
    server, _ = build_server(EVERY_PROFILE, comfyui=comfyui_answering())
    sdk = {t.name: t.input_schema for t in await MCPServer.list_tools(server)}
    async with Client(server, mode="legacy") as client:
        wire = {t.name: t.input_schema for t in (await client.list_tools()).tools}
    assert wire.keys() == sdk.keys()
    for name, schema in sdk.items():
        assert wire[name] == _without_titles(schema), name
