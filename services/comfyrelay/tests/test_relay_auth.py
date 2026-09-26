"""The token: the server refuses to start without one, and every request
without the right one gets 401 before the MCP layer sees it."""

from __future__ import annotations

import httpx2
import pytest
from comfyrelay.server import TokenAuth
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


# -- ASGI scopes: http behind the token, lifespan through, nothing else -------


async def _through(scope: dict, incoming: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    """Run TokenAuth once. Returns (scopes the wrapped app saw, messages sent back)."""
    reached, sent = [], []
    queue = list(incoming or [])

    async def inner(scope, receive, send):
        reached.append(scope)

    async def receive():
        return queue.pop(0)

    async def send(message):
        sent.append(message)

    await TokenAuth(inner, TOKEN)(scope, receive, send)
    return reached, sent


@pytest.mark.anyio
async def test_lifespan_passes_through():
    reached, sent = await _through({"type": "lifespan"})
    assert [s["type"] for s in reached] == ["lifespan"] and sent == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    "headers", [[], [(b"authorization", f"Bearer {TOKEN}".encode())]], ids=["no-token", "with-the-token"]
)
async def test_a_websocket_is_refused_whatever_it_carries(headers):
    scope = {"type": "websocket", "path": "/mcp", "headers": headers, "client": ("10.0.0.9", 5000)}
    reached, sent = await _through(scope, [{"type": "websocket.connect"}])
    assert reached == []
    assert sent == [{"type": "websocket.close", "code": 1008}]


@pytest.mark.anyio
async def test_an_unknown_scope_is_not_forwarded():
    reached, sent = await _through({"type": "webtransport", "headers": [(b"x-api-key", TOKEN.encode())]})
    assert reached == [] and sent == []


@pytest.mark.anyio
async def test_http_with_the_token_is_forwarded():
    scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": [(b"x-api-key", TOKEN.encode())]}
    reached, _ = await _through(scope)
    assert reached == [scope]


# -- COMFYUI_URL is checked at startup ----------------------------------------


@pytest.mark.parametrize(
    "url",
    ["http://[::1", "http://comfyui:notaport", "ftp://comfyui:8188", "comfyui:8188", "http://", "not a url"],
)
def test_a_malformed_comfyui_url_is_a_config_error(url):
    with pytest.raises(ConfigError, match="COMFYUI_URL"):
        Settings.load(comfyui_url=url, host="0.0.0.0", port=9000, profiles="read", env={TOKEN_ENV: TOKEN})


@pytest.mark.parametrize(
    "url", ["http://localhost:8188", "https://comfy.example/", "http://[::1]:8188", "http://u:p@comfyui:8188"]
)
def test_a_valid_comfyui_url_is_accepted(url):
    s = Settings.load(comfyui_url=url, host="0.0.0.0", port=9000, profiles="read", env={TOKEN_ENV: TOKEN})
    assert s.comfyui_url == url
