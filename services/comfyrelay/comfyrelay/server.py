"""Build the MCP server and serve it over streamable HTTP, behind the token.

The token check is ASGI middleware around the whole app, so it runs before
the MCP layer parses anything: no route, and no MCP method, is reachable
without the token. It accepts `Authorization: Bearer <token>` or
`X-API-Key: <token>`, the two forms the `mcp` image accepts today, and compares
in constant time. Anything else gets 401. Only two ASGI scopes exist here:
`http`, behind the token, and `lifespan`, which the server itself sends. Every
other scope, a websocket included, is refused whatever it carries.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

import uvicorn
from mcp.server.mcpserver import MCPServer

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

from . import __version__
from .comfyui import ComfyUIClient
from .jobs import JobStore
from .settings import INSTANCE_ID_ENV, MCP_PATH, Settings, redact_url
from .tools import SERVER_NAME, Relay, register

log = logging.getLogger("comfyrelay")

# How long a stop waits for jobs to unwind, and then for everything else. With
# uvicorn's 3s graceful shutdown that is at most 9s, inside the 10s Docker and
# Kubernetes allow by default between SIGTERM (tini forwards it) and SIGKILL.
SHUTDOWN_WAIT_SECONDS = 3.0

INSTRUCTIONS = """\
comfyrelay drives one ComfyUI instance. Call server_info first: it names the instance, its active capability \
profiles, and the ComfyUI version it serves. Work that outlasts one call returns a job_id; follow it with \
job_status, and stop it with job_cancel. This server installs, updates and restarts nothing. A failed call's text \
ends in JSON: {"error": {"code", "message", "retryable"}}."""


def build_server(settings: Settings, *, comfyui: ComfyUIClient | None = None) -> tuple[MCPServer, Relay]:
    relay = Relay(
        settings=settings,
        comfyui=comfyui or ComfyUIClient(settings.comfyui_url),
        jobs=JobStore(max_in_flight=settings.max_jobs),
    )
    server = MCPServer(SERVER_NAME, version=__version__, instructions=INSTRUCTIONS)
    register(server, relay)
    return server, relay


class TokenAuth:
    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self._token = token.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan" or (scope["type"] == "http" and self._authorized(scope)):
            await self.app(scope, receive, send)
            return
        client = scope.get("client") or ("?", 0)
        if scope["type"] == "websocket":
            # Closing before accepting refuses the handshake (HTTP 403).
            log.warning("refused a websocket to %s from %s: this server has none", scope.get("path"), client[0])
            await receive()  # websocket.connect
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            log.warning("refused an ASGI %r scope: only http is served", scope["type"])
            return
        log.warning("401 for %s %s from %s: missing or wrong token", scope["method"], scope["path"], client[0])
        body = json.dumps({"error": "unauthorized", "message": "send the server's token as a Bearer token"})
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b'Bearer realm="comfyrelay"'),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body.encode()})

    def _authorized(self, scope: Scope) -> bool:
        headers = dict(scope.get("headers") or [])
        presented = headers.get(b"x-api-key")
        auth = headers.get(b"authorization", b"")
        scheme, _, credential = auth.partition(b" ")
        if scheme.lower() == b"bearer":
            presented = credential.strip()
        return presented is not None and hmac.compare_digest(presented, self._token)


def http_app(server: MCPServer, settings: Settings) -> Any:
    app = server.streamable_http_app(streamable_http_path=MCP_PATH, host=settings.host)
    return TokenAuth(app, settings.token)


def serve(settings: Settings) -> None:
    server, relay = build_server(settings)
    log.info(
        "comfyrelay %s on http://%s:%d%s, instance %s, profiles %s, tools %s, ComfyUI at %s (built for %s)",
        __version__,
        settings.host,
        settings.port,
        MCP_PATH,
        settings.instance_id,
        ",".join(settings.profiles),
        ",".join(relay.tools),
        redact_url(settings.comfyui_url),
        settings.comfyui_pin or "unknown",
    )
    if settings.instance_id_source == "hostname":
        log.warning(
            "%s is not set, so the instance id is the hostname %r, which can change when the container or pod "
            "is recreated. Set it to a stable name if a gateway federates this sidecar.",
            INSTANCE_ID_ENV,
            settings.instance_id,
        )
    config = uvicorn.Config(
        http_app(server, settings),
        host=settings.host,
        port=settings.port,
        # Our logging, not uvicorn's dictConfig; no per-request access lines.
        log_config=None,
        access_log=False,
        # A stop must not wait on open SSE streams for long.
        timeout_graceful_shutdown=3,
    )
    run_until_stopped(
        uvicorn.Server(config).serve(), relay.jobs, wait=SHUTDOWN_WAIT_SECONDS, loop_factory=config.get_loop_factory()
    )


def run_until_stopped(
    main: Coroutine[Any, Any, None],
    jobs: JobStore,
    *,
    wait: float = SHUTDOWN_WAIT_SECONDS,
    loop_factory: Callable[[], asyncio.AbstractEventLoop] | None = None,
) -> None:
    """Run `main` (the server) to completion, then stop every job, with every wait bounded.

    This replaces `asyncio.run`, which uvicorn's `Server.run` uses: its cleanup
    cancels every remaining task and then waits for all of them WITHOUT a
    limit, so one job whose producer swallows CancelledError in a loop would
    keep the process alive until `docker stop` escalates to SIGKILL. Here the
    jobs get `wait` seconds (JobStore.shutdown logs any that overrun), then
    every other task gets `wait` seconds, then the loop closes regardless.
    """
    loop = (loop_factory or asyncio.new_event_loop)()
    try:
        loop.run_until_complete(main)
    finally:
        try:
            loop.run_until_complete(jobs.shutdown(wait))
            rest = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for task in rest:
                task.cancel()
            if rest:
                loop.run_until_complete(asyncio.wait(rest, timeout=wait))
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            loop.close()
