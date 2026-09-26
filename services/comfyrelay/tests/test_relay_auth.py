"""The token: the server refuses to start without one, and every request
without the right one gets 401 before the MCP layer sees it."""

from __future__ import annotations

import httpx2
import pytest
from comfyrelay.settings import TOKEN_ENV, ConfigError, Settings
from relay_helpers import TOKEN

INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
}
ACCEPT = {"Accept": "application/json, text/event-stream"}


def load(env):
    return Settings.load(comfyui_url="http://x", host="0.0.0.0", port=9000, profiles="read,run", env=env)


@pytest.mark.parametrize("env", [{}, {TOKEN_ENV: ""}, {TOKEN_ENV: "   "}])
def test_refuses_to_start_without_a_token(env):
    with pytest.raises(ConfigError, match=f"Refusing to start: {TOKEN_ENV} is not set"):
        load(env)


def test_starts_with_a_token():
    assert load({TOKEN_ENV: " s3cret "}).token == "s3cret"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": f"Basic {TOKEN}"},
        {"Authorization": f"Bearer {TOKEN}x"},
        {"X-API-Key": "wrong"},
        {"Authorization": "Bearer"},
    ],
    ids=["none", "wrong-bearer", "not-bearer", "prefix-of-token", "wrong-api-key", "empty-bearer"],
)
def test_requests_without_the_right_token_get_401(live_server, headers):
    r = httpx2.post(live_server, json=INIT, headers={**ACCEPT, **headers})
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Bearer")
    assert r.json()["error"] == "unauthorized"


def test_every_path_is_behind_the_token(live_server):
    """Not just /mcp: nothing on this port answers anonymously."""
    for path in ("/", "/mcp", "/health", "/docs"):
        assert httpx2.get(live_server.replace("/mcp", path)).status_code == 401


@pytest.mark.parametrize(
    "headers", [{"Authorization": f"Bearer {TOKEN}"}, {"authorization": f"bearer {TOKEN}"}, {"X-API-Key": TOKEN}]
)
def test_the_right_token_reaches_mcp(live_server, headers):
    r = httpx2.post(live_server, json=INIT, headers={**ACCEPT, **headers})
    assert r.status_code == 200
    assert "comfyrelay" in r.text
