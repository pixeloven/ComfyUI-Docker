"""UI-to-API workflow conversion through the instance's own frontend (#167, D1). SPIKE.

ComfyUI has no conversion route, so the relay drives a headless Chromium
against the frontend that COMFYUI_URL serves, loads the UI graph with
`app.loadGraphData(wf, true, false, null)` and returns
`(await app.graphToPrompt()).output`: the same API graph the editor's
Export (API) writes, because it IS the editor. There is no fallback converter
(D5): a failure is `conversion_unavailable` (no browser, no frontend) or
`conversion_failed` (the frontend threw), with the reason.

Off unless COMFYUI_MCP_CONVERT=1, and it needs the `convert` extra
(Playwright) and a Chromium; the mcp image installs both only when built with
RELAY_CONVERT=1.

Lockdown (D3), enforced here in code: the browser may make GET requests to
the COMFYUI_URL origin and nothing else. Every other request, of any method
to any other host and every non-GET to ComfyUI, is aborted, and every
websocket (ComfyUI's /ws included) is closed before it connects. The relay
never queues a prompt from the page, so no `extra_data` and no credentials
reach ComfyUI from here, and a COMFYUI_URL that carries credentials is
refused rather than handed to the browser.

One browser per relay, started on first use and reused. `pages` tabs each
hold a loaded frontend; a conversion takes one, so at most `pages` run at
once and the rest wait. A tab whose conversion failed is replaced, so a
frontend left in a bad state is not reused, and so is a tab after
RECYCLE_AFTER conversions, because the frontend keeps every graph it loaded.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import os
import re
from typing import Any
from urllib.parse import urlsplit

from .errors import RelayError
from .settings import redact_url

log = logging.getLogger("comfyrelay.convert")

# Where the mcp image puts Chromium when built with RELAY_CONVERT=1.
IMAGE_BROWSERS_PATH = "/opt/playwright"
# Each conversion leaves the frontend holding one more open (temporary) workflow, and the tab's memory grows
# with them (#167 spike: about 5 MB a conversion), so a tab is replaced after this many.
RECYCLE_AFTER = 25
# Request interception sees HTTP(S) and websockets, not WebRTC: without the policy flag, a page script's
# RTCPeerConnection sends STUN over UDP to any host it names (#167 spike, measured). With it, and no proxy,
# WebRTC has no UDP at all.
LAUNCH_ARGS = ["--disable-dev-shm-usage", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"]
READY_TIMEOUT_SECONDS = 60.0
CONVERT_TIMEOUT_SECONDS = 30.0
_DEFAULT_PORTS = {"http": 80, "https": 443}
_READY = "() => !!(window.app && window.app.graphToPrompt && window.app.loadGraphData && window.app.vueAppReady)"
# Through JSON, as the editor's Export (API) writes it: a key whose value is undefined (class_type of a node
# type this instance lacks) is dropped, where Playwright would hand it over as null.
_CONVERT = """async (wf) => {
  await window.app.loadGraphData(wf, true, false, null);
  return JSON.parse(JSON.stringify((await window.app.graphToPrompt()).output));
}"""


def is_ui_format(graph: Any) -> bool:
    """The test workflow.shape_problems uses to refuse a UI-format graph."""
    return isinstance(graph, dict) and isinstance(graph.get("nodes"), list) and "links" in graph


def _origin(url: str) -> tuple[str, str, int] | None:
    try:
        parts = urlsplit(url)
        port = parts.port or _DEFAULT_PORTS.get(parts.scheme)
    except ValueError:
        return None
    if parts.scheme not in _DEFAULT_PORTS or not parts.hostname or port is None:
        return None
    return parts.scheme, parts.hostname.lower(), port


def unavailable(reason: str, **detail: Any) -> RelayError:
    return RelayError(
        "conversion_unavailable",
        f"UI-to-API conversion is unavailable: {reason}. Nothing was converted; there is no fallback converter.",
        retryable=False,
        **detail,
    )


def failed(reason: str, **detail: Any) -> RelayError:
    return RelayError(
        "conversion_failed",
        f"the instance's frontend could not convert this workflow: {reason}",
        retryable=False,
        **detail,
    )


class Converter:
    def __init__(self, comfyui_url: str, *, pages: int = 2) -> None:
        self.url = comfyui_url
        self.pages = pages
        self.origin = _origin(comfyui_url)
        parts = urlsplit(comfyui_url)
        self._refused: str | None = None
        if parts.username or parts.password:
            self._refused = "COMFYUI_URL carries credentials, which this spike never hands to the browser"
        elif self.origin is None:
            self._refused = f"COMFYUI_URL {redact_url(comfyui_url)!r} has no http(s) origin"
        # What the lockdown stopped, newest last: (method or "WS", url). For tests and the spike's report.
        self.blocked: collections.deque[tuple[str, str]] = collections.deque(maxlen=200)
        self._start_lock = asyncio.Lock()
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._idle: asyncio.Queue[Any] = asyncio.Queue()
        self._replacing: set[asyncio.Future[Any]] = set()
        self._uses: dict[int, int] = {}

    # -- lockdown (D3) --------------------------------------------------------

    def allowed(self, method: str, url: str) -> bool:
        return method == "GET" and _origin(url) == self.origin

    async def _gate(self, route: Any, request: Any) -> None:
        if self.allowed(request.method, request.url):
            await route.continue_()
            return
        self.blocked.append((request.method, request.url))
        await route.abort("blockedbyclient")

    async def _gate_ws(self, ws: Any) -> None:
        # Not calling connect_to_server means the socket never reaches its server.
        self.blocked.append(("WS", ws.url))
        await ws.close()

    # -- lifecycle -------------------------------------------------------------

    async def _new_page(self) -> Any:
        page = await self._context.new_page()
        await page.goto(self.url, wait_until="networkidle", timeout=READY_TIMEOUT_SECONDS * 1000)
        await page.wait_for_function(_READY, polling=250, timeout=READY_TIMEOUT_SECONDS * 1000)
        return page

    async def _start(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise unavailable(
                "Playwright is not installed (the mcp image installs it only when built with RELAY_CONVERT=1)"
            ) from None
        if os.path.isdir(IMAGE_BROWSERS_PATH):
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", IMAGE_BROWSERS_PATH)
        try:
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(headless=True, args=LAUNCH_ARGS)
            self._context = await self._browser.new_context(service_workers="block", accept_downloads=False)
            await self._context.route("**/*", self._gate)
            await self._context.route_web_socket(re.compile(r".*"), self._gate_ws)
            for page in await asyncio.gather(*(self._new_page() for _ in range(self.pages))):
                self._idle.put_nowait(page)
        except Exception as exc:
            await self.close()
            raise unavailable(
                f"the browser or the frontend did not start: {type(exc).__name__}: {str(exc)[:300]}"
            ) from None

    async def close(self) -> None:
        browser, pw = self._browser, self._pw
        self._browser = self._pw = self._context = None
        self._idle = asyncio.Queue()
        for closing in (browser and browser.close(), pw and pw.stop()):
            if closing is not None:
                try:
                    await closing
                except Exception:  # already gone
                    pass

    # -- conversion ------------------------------------------------------------

    async def convert(self, workflow: dict[str, Any]) -> dict[str, Any]:
        """The API graph the frontend makes of `workflow`, or RelayError conversion_unavailable/_failed."""
        if self._refused:
            raise unavailable(self._refused)
        async with self._start_lock:
            if self._browser is None:
                await self._start()
        try:
            page = await asyncio.wait_for(self._idle.get(), READY_TIMEOUT_SECONDS)
        except TimeoutError:
            raise unavailable(f"no converter tab came free in {READY_TIMEOUT_SECONDS:.0f}s") from None
        healthy = False
        self._uses[id(page)] = uses = self._uses.get(id(page), 0) + 1
        try:
            output = await asyncio.wait_for(page.evaluate(_CONVERT, workflow), CONVERT_TIMEOUT_SECONDS)
            healthy = True
        except TimeoutError:
            raise failed(f"no answer in {CONVERT_TIMEOUT_SECONDS:.0f}s") from None
        except Exception as exc:
            raise failed(f"{type(exc).__name__}: {str(exc)[:500]}") from None
        finally:
            if healthy and uses < RECYCLE_AFTER:
                self._idle.put_nowait(page)
            else:
                task = asyncio.ensure_future(self._replace(page))
                self._replacing.add(task)
                task.add_done_callback(self._replacing.discard)
        if not isinstance(output, dict):
            raise failed(f"graphToPrompt returned {type(output).__name__}, not an object")
        return output

    async def _replace(self, page: Any) -> None:
        self._uses.pop(id(page), None)
        try:
            await page.close()
        except Exception:
            pass
        try:
            self._idle.put_nowait(await self._new_page())
        except Exception as exc:  # a pool one tab short; the spike logs it rather than recovering
            log.warning("could not replace a converter tab: %s: %s", type(exc).__name__, exc)
