"""Helpers the tests import. Uniquely named, because `import conftest` would be
ambiguous: services/fetch/tests has a conftest.py too, and one pytest run
collects both."""

from __future__ import annotations

import socket
from collections.abc import Callable

import httpx2
from comfyrelay.comfyui import ComfyUIClient
from comfyrelay.settings import Settings

TOKEN = "test-token-0123456789"
SYSTEM_STATS = {
    "system": {"os": "posix", "comfyui_version": "0.37.0", "python_version": "3.12.3"},
    "devices": [{"name": "cpu", "type": "cpu"}],
}


def comfyui_answering(routes: dict[str, httpx2.Response] | None = None) -> ComfyUIClient:
    """A ComfyUIClient whose ComfyUI answers from `routes` (path -> response), 404 otherwise."""
    routes = {"/system_stats": httpx2.Response(200, json=SYSTEM_STATS), **(routes or {})}

    def handler(request: httpx2.Request) -> httpx2.Response:
        return routes.get(request.url.raw_path.decode(), routes.get(request.url.path, httpx2.Response(404)))

    return ComfyUIClient("http://comfyui.test:8188", transport=httpx2.MockTransport(handler))


def comfyui_raising(exc: Callable[[httpx2.Request], Exception]) -> ComfyUIClient:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise exc(request)

    return ComfyUIClient("http://comfyui.test:8188", transport=httpx2.MockTransport(handler))


def settings(**overrides) -> Settings:
    base = dict(
        token=TOKEN,
        comfyui_url="http://comfyui.test:8188",
        host="127.0.0.1",
        port=9000,
        profiles=("read", "run"),
        instance_id="test-instance",
        comfyui_pin="v0.37.0",
    )
    return Settings(**{**base, **overrides})


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
