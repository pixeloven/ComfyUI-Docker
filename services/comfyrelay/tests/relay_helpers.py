"""Helpers the tests import. Uniquely named, because `import conftest` would be
ambiguous: services/fetch/tests has a conftest.py too, and one pytest run
collects both."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Awaitable, Callable
from typing import Any

import httpx2
from comfyrelay.comfyui import ComfyUIClient
from comfyrelay.jobs import SHUTDOWN_WAIT_SECONDS, JobState, JobStore
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


async def serve_nothing(self, sockets=None) -> None:
    """Stands in for uvicorn.Server.serve: `serve()` runs everything but the listening."""


async def assert_producer_honours_cancel(
    work: Callable[[], Awaitable[Any]], *, started: asyncio.Event | None = None, within: float = SHUTDOWN_WAIT_SECONDS
) -> None:
    """The producer contract (comfyrelay/jobs.py): cancelled, a producer stops within
    SHUTDOWN_WAIT_SECONDS (3s, its budget when the server stops) by letting
    CancelledError propagate. Every job producer's tests call this with its real
    work, and with `started` if it has a point where it is well under way (set it
    there), so the cancel lands mid-work, not before it began. It cannot see into
    threads: work handed to one must be interruptible on its own (the contract's
    second rule).
    """
    store = JobStore(cancel_wait=within)
    job = store.submit("contract.check", work)
    if started is not None:
        await asyncio.wait_for(started.wait(), 10)
    else:
        await asyncio.sleep(0.05)
    assert not job.task.done(), "the producer finished before it could be cancelled; set `started` mid-work"
    await store.cancel(job.id)
    assert job.task.done(), f"the producer did not stop within {within}s of being cancelled"
    assert job.task.cancelled(), "the producer swallowed CancelledError; it must re-raise it"
    assert job.state is JobState.cancelled
