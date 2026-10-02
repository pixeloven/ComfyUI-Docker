"""LargeBodyGate (#136): at most COMFYUI_MCP_MAX_LARGE_REQUESTS requests with a body over 1 MiB are handled at
once. One more waits a bounded time for a slot, then gets a retryable 503; small requests never wait."""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from comfyrelay.server import LARGE_BODY_BYTES, LargeBodyGate, TokenAuth, build_server, http_app
from comfyrelay.settings import MAX_LARGE_REQUESTS_ENV, TOKEN_ENV, ConfigError, Settings
from relay_helpers import TOKEN, comfyui_answering, settings

BIG = LARGE_BODY_BYTES + 1


class Held:
    """A transport stand-in that holds every request until released, and counts who got in."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.inside = 0
        self.most_inside = 0

    async def __call__(self, scope, receive, send):
        self.inside += 1
        self.most_inside = max(self.most_inside, self.inside)
        try:
            await self.release.wait()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})
        finally:
            self.inside -= 1


async def request(gate, headers):
    scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": headers}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await gate(scope, receive, send)
    return sent


def length(n: int) -> list[tuple[bytes, bytes]]:
    return [(b"content-length", str(n).encode())]


async def until(condition, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        await asyncio.sleep(0.01)


@pytest.mark.anyio
async def test_past_the_limit_a_large_request_waits_the_bound_then_gets_a_retryable_503():
    app = Held()
    gate = LargeBodyGate(app, 2, wait=0.3)
    held = [asyncio.create_task(request(gate, length(BIG))) for _ in range(2)]
    await until(lambda: app.inside == 2)

    started = time.monotonic()
    sent = await request(gate, length(BIG))
    waited = time.monotonic() - started

    assert 0.25 <= waited < 1.0, waited
    assert sent[0]["status"] == 503
    assert dict(sent[0]["headers"])[b"retry-after"] == b"2"
    error = json.loads(sent[1]["body"])["error"]
    assert error["code"] == "server_busy" and error["retryable"] is True
    assert app.most_inside == 2, "the refused request reached the transport"

    app.release.set()
    assert [(await t)[0]["status"] for t in held] == [200, 200]


@pytest.mark.anyio
async def test_a_waiting_large_request_takes_the_first_slot_that_frees():
    app = Held()
    gate = LargeBodyGate(app, 1, wait=5)
    first = asyncio.create_task(request(gate, length(BIG)))
    await until(lambda: app.inside == 1)
    second = asyncio.create_task(request(gate, length(BIG)))
    await asyncio.sleep(0.05)
    assert app.inside == 1 and not second.done()

    app.release.set()
    started = time.monotonic()
    assert (await second)[0]["status"] == 200
    assert time.monotonic() - started < 1.0
    assert (await first)[0]["status"] == 200
    assert app.most_inside == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "headers",
    [length(LARGE_BODY_BYTES), length(0), []],
    ids=["exactly-the-threshold", "empty", "no-body"],
)
async def test_small_and_bodyless_requests_never_wait(headers):
    app = Held()
    gate = LargeBodyGate(app, 1, wait=5)
    blocker = asyncio.create_task(request(gate, length(BIG)))
    await until(lambda: app.inside == 1)
    small = asyncio.create_task(request(gate, headers))
    await until(lambda: app.inside == 2, timeout=0.5)
    app.release.set()
    assert (await small)[0]["status"] == 200
    await blocker


@pytest.mark.anyio
@pytest.mark.parametrize(
    "headers",
    [[(b"transfer-encoding", b"chunked")], [(b"content-length", b"lots")]],
    ids=["chunked", "unreadable-length"],
)
async def test_a_body_of_unknown_length_counts_as_large(headers):
    app = Held()
    gate = LargeBodyGate(app, 1, wait=0.1)
    blocker = asyncio.create_task(request(gate, length(BIG)))
    await until(lambda: app.inside == 1)
    assert (await request(gate, headers))[0]["status"] == 503
    app.release.set()
    await blocker


@pytest.mark.anyio
async def test_a_failing_request_gives_its_slot_back():
    async def broken(scope, receive, send):
        raise RuntimeError("boom")

    gate = LargeBodyGate(broken, 1, wait=0.1)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await request(gate, length(BIG))


@pytest.mark.anyio
async def test_lifespan_and_other_scopes_pass_straight_through():
    reached = []

    async def inner(scope, receive, send):
        reached.append(scope["type"])

    await LargeBodyGate(inner, 1)({"type": "lifespan"}, None, None)
    assert reached == ["lifespan"]


def test_the_limit_comes_from_the_environment():
    def load(env):
        return Settings.load(comfyui_url="http://x", host="h", port=1, profiles="run", env={TOKEN_ENV: TOKEN, **env})

    assert load({}).max_large_requests == 2
    assert load({MAX_LARGE_REQUESTS_ENV: "5"}).max_large_requests == 5
    for bad in ("0", "-1", "many", "2.5"):
        with pytest.raises(ConfigError, match=MAX_LARGE_REQUESTS_ENV):
            load({MAX_LARGE_REQUESTS_ENV: bad})


def test_the_gate_sits_behind_the_token_with_the_configured_limit():
    s = settings(max_large_requests=3)
    server, _ = build_server(s, comfyui=comfyui_answering())
    app = http_app(server, s)
    assert isinstance(app, TokenAuth)
    assert isinstance(app.app, LargeBodyGate) and app.app.limit == 3
