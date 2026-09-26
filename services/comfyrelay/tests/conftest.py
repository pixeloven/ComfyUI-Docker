"""Fixtures. ComfyUI is faked with httpx2's MockTransport (httpx2 is the SDK's
HTTP client, and respx patches only httpx); MCP runs in memory through the
SDK's own Client, or over real HTTP through `live_server`."""

from __future__ import annotations

import threading
import time

import pytest
import uvicorn
from comfyrelay.server import build_server, http_app
from relay_helpers import comfyui_answering, free_port, settings


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def live_server():
    """comfyrelay over real HTTP on a free loopback port, with a fake ComfyUI. Yields the /mcp URL."""
    s = settings(port=free_port())
    server, _relay = build_server(s, comfyui=comfyui_answering())
    config = uvicorn.Config(http_app(server, s), host=s.host, port=s.port, log_config=None, access_log=False)
    uv = uvicorn.Server(config)
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not uv.started:
        assert time.time() < deadline, "the test server did not start"
        time.sleep(0.05)
    yield f"http://{s.host}:{s.port}/mcp"
    uv.should_exit = True
    thread.join(10)
