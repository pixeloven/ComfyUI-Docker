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
    assert load({TOKEN_ENV: f" {TOKEN} "}).token == TOKEN


def test_refuses_to_start_with_a_token_under_32_characters_and_says_how_to_make_one():
    short = "s3cret-but-only-31-characters-x"
    assert len(short) == 31
    with pytest.raises(ConfigError) as info:
        load({TOKEN_ENV: short})
    message = str(info.value)
    assert message.startswith(f"Refusing to start: {TOKEN_ENV} is 31 characters")
    assert "at least 32" in message and "openssl rand -hex 32" in message
    assert short not in message
    assert load({TOKEN_ENV: short + "y"}).token == short + "y"


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


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "Bearer the-gateways-own-credential", "X-API-Key": TOKEN},
        {"Authorization": f"Bearer {TOKEN}", "X-API-Key": "something-else"},
        {"Authorization": "Basic dXNlcjpwYXNz", "X-API-Key": TOKEN},
    ],
    ids=["wrong-bearer-right-api-key", "right-bearer-wrong-api-key", "basic-auth-right-api-key"],
)
def test_either_header_carrying_the_token_is_enough(live_server, headers):
    """As artokun did: a gateway can send its own Bearer and pass this server's token in X-API-Key."""
    r = httpx2.post(live_server, json=INIT, headers={**ACCEPT, **headers})
    assert r.status_code == 200


def test_both_headers_wrong_get_401(live_server):
    r = httpx2.post(live_server, json=INIT, headers={**ACCEPT, "Authorization": "Bearer no", "X-API-Key": "no"})
    assert r.status_code == 401


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
async def test_a_large_body_without_the_token_is_refused_before_it_is_read():
    """The run profile raises the body limit to fit uploads; without the token not one byte of the body is read."""
    size = 20 * 1024 * 1024  # past the SDK's 4 MiB and the run profile's limit alike
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(b"content-length", str(size).encode()), (b"content-type", b"application/json")],
        "client": ("10.0.0.9", 5000),
    }
    reads, sent = [], []

    async def receive():
        reads.append(1)
        return {"type": "http.request", "body": b"x" * 65536, "more_body": True}

    async def send(message):
        sent.append(message)

    async def inner(*_):
        raise AssertionError("the app must not be reached")

    await TokenAuth(inner, TOKEN)(scope, receive, send)
    assert reads == []
    assert sent[0]["type"] == "http.response.start" and sent[0]["status"] == 401


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


@pytest.mark.parametrize("public_url", [None, "", "   "])
def test_public_output_links_are_opt_in_even_with_a_private_comfyui_url(public_url):
    env = {TOKEN_ENV: TOKEN}
    if public_url is not None:
        env["COMFYUI_PUBLIC_URL"] = public_url
    s = Settings.load(
        comfyui_url="http://private-user:private-secret@internal:8188", host="h", port=1, profiles="run", env=env
    )
    assert s.comfyui_public_url is None


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://comfy.example", "https://comfy.example"),
        ("https://comfy.example/", "https://comfy.example"),
        ("https://comfy.example:8443/team/comfy/", "https://comfy.example:8443/team/comfy"),
        ("http://localhost:8188", "http://localhost:8188"),
        ("http://127.0.0.1:8188/", "http://127.0.0.1:8188"),
        ("http://[::1]:8188/comfy/", "http://[::1]:8188/comfy"),
        ("https://münich.example/réfs/%2F/", "https://xn--mnich-kva.example/r%C3%A9fs/%2F"),
    ],
)
def test_public_output_base_accepts_http_hosts_and_preserves_a_proxy_prefix(url, expected):
    s = load({TOKEN_ENV: TOKEN, "COMFYUI_PUBLIC_URL": url})
    assert s.comfyui_public_url == expected


@pytest.mark.parametrize(
    "url",
    [
        "ftp://host/path", "//host/path", "host/path", "https:///path", "https://[::1",
        "https://host:bad", "https://host:65536", "https://host:0", "https://host:",
        "https://u:private-secret@host", "https://private-secret@host", "https://host?token=private-secret",
        "http://admin:12/ss@comfyui:8188",
        "https://host#private-secret", "https://host/comfy?", "https://host/comfy#",
        " https://host", "https://host ", "https://ho\tst", "https://ho\nst", "https://host/a b",
        "https://host/\x00", "https://host/\x7f", "https://host\\@elsewhere", "https://host/a\\b",
        "https://host%40elsewhere", "https://host|other", "https://-host", "https://host..example",
        "https://host..", "https://256.256.256.256", "https://exämple..",
    ],
)
def test_public_output_base_refuses_ambiguous_urls_without_echoing_values(url):
    with pytest.raises(ConfigError) as info:
        load({TOKEN_ENV: TOKEN, "COMFYUI_PUBLIC_URL": url})
    assert str(info.value).startswith("COMFYUI_PUBLIC_URL must be an http:// or https:// URL")
    assert url not in str(info.value)
    assert "private-secret" not in str(info.value)
