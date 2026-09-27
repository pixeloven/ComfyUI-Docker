"""server_info: identity, profiles, capabilities, the pinned and live ComfyUI
versions, and the corpus placeholder."""

from __future__ import annotations

import logging
import socket

import httpx2
import pytest
import uvicorn
from comfyrelay import __version__
from comfyrelay.server import build_server, serve
from comfyrelay.settings import Settings
from mcp import Client
from relay_helpers import comfyui_answering, comfyui_raising, serve_nothing, settings

pytestmark = pytest.mark.anyio


async def info(s=None, comfyui=None, elicitation=False) -> dict:
    server, _ = build_server(s or settings(), comfyui=comfyui or comfyui_answering())

    async def never(context, params):  # declaring a callback declares the capability
        raise AssertionError("server_info must not elicit")

    async with Client(server, mode="legacy", elicitation_callback=never if elicitation else None) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        result = await client.call_tool("server_info", {})
    assert not result.is_error, result.content
    assert tools["server_info"].output_schema is not None
    assert tools["server_info"].annotations.read_only_hint is True
    return result.structured_content


async def test_identity_and_profiles():
    got = await info(settings(instance_id="pod-7"))
    assert got["name"] == "comfyrelay"
    assert got["version"] == __version__
    assert got["instance_id"] == "pod-7"
    assert got["instance_id_source"] == "env"
    assert got["profiles"] == {
        "active": ["read", "run"],
        "available": ["read", "run", "manage", "develop"],
        "without_tools": [],
    }


async def test_capabilities():
    got = await info()
    assert got["capabilities"]["tools"] == [
        "job_cancel",
        "job_status",
        "model_list",
        "node_describe",
        "node_search",
        "server_info",
        "template_get",
        "template_search",
    ]
    assert got["capabilities"]["consent"] == {"policy": "refuse-all", "client_can_elicit": False}
    assert got["capabilities"]["jobs"] == {"store": "memory", "max_wait_seconds": 300.0, "max_in_flight": 16}
    assert (await info(settings(max_jobs=3)))["capabilities"]["jobs"]["max_in_flight"] == 3
    assert (await info(elicitation=True))["capabilities"]["consent"]["client_can_elicit"] is True


async def test_live_version_matches_the_pin():
    got = await info()
    assert got["comfyui"] == {
        "reachable": True,
        "live_version": "0.37.0",
        "pinned_version": "v0.37.0",
        "matches_pin": True,
        "error": None,
    }


@pytest.mark.parametrize(
    ("pin", "matches"),
    [("v0.36.0", False), ("0.37.0", True), ("0123abcd" * 5, None), (None, None)],
    ids=["older-pin", "no-v-prefix", "commit-pin", "outside-the-image"],
)
async def test_pin_comparison(pin, matches):
    got = await info(settings(comfyui_pin=pin))
    assert got["comfyui"]["pinned_version"] == pin
    assert got["comfyui"]["matches_pin"] is matches


async def test_unreachable_comfyui_is_reported_not_raised():
    got = await info(comfyui=comfyui_raising(lambda r: httpx2.ConnectError("refused", request=r)))
    assert got["comfyui"]["reachable"] is False
    assert got["comfyui"]["live_version"] is None
    assert got["comfyui"]["matches_pin"] is None
    assert got["comfyui"]["error"]["code"] == "comfyui_unreachable"
    assert got["comfyui"]["error"]["retryable"] is True


async def test_corpus_is_a_placeholder_until_it_is_built():
    assert (await info())["corpus"] == {"status": "absent", "sources": []}


def test_instance_id_and_pin_come_from_the_environment(monkeypatch):
    env = {
        "COMFYUI_MCP_HTTP_TOKEN": "t",
        "COMFYUI_MCP_INSTANCE_ID": "comfy-a",
        "COMFYUI_VERSION": "v0.37.0",
    }
    s = Settings.load(comfyui_url="http://x", host="0.0.0.0", port=9000, profiles="read", env=env)
    assert (s.instance_id, s.instance_id_source, s.comfyui_pin) == ("comfy-a", "env", "v0.37.0")
    s = Settings.load(
        comfyui_url="http://x", host="0.0.0.0", port=9000, profiles="read", env={"COMFYUI_MCP_HTTP_TOKEN": "t"}
    )
    assert s.instance_id == socket.gethostname()
    assert s.instance_id_source == "hostname"
    assert s.comfyui_pin is None


async def test_a_hostname_instance_id_is_reported_as_such():
    assert (await info(settings(instance_id_source="hostname")))["instance_id_source"] == "hostname"


def test_startup_warns_when_the_instance_id_is_the_hostname(monkeypatch, caplog):
    """A federating gateway needs stable ids; a hostname is not one."""
    monkeypatch.setattr(uvicorn.Server, "serve", serve_nothing)
    caplog.set_level(logging.INFO, logger="comfyrelay")
    serve(settings(instance_id="abc123", instance_id_source="hostname"))
    assert "COMFYUI_MCP_INSTANCE_ID is not set, so the instance id is the hostname 'abc123'" in caplog.text
    caplog.clear()
    serve(settings())
    assert "COMFYUI_MCP_INSTANCE_ID" not in caplog.text


@pytest.mark.parametrize(
    "body",
    [[], {"system": None}, {"system": "0.37.0"}, {"devices": []}, "0.37.0"],
    ids=["a-list", "null-system", "string-system", "no-system", "a-string"],
)
async def test_a_misshapen_system_stats_is_reported_not_raised(body):
    got = await info(comfyui=comfyui_answering({"/system_stats": httpx2.Response(200, json=body)}))
    assert got["comfyui"]["reachable"] is False
    assert got["comfyui"]["live_version"] is None
    assert got["comfyui"]["error"]["code"] == "comfyui_bad_response"
    assert got["comfyui"]["error"]["retryable"] is False
