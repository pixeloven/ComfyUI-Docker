"""UI-to-API workflow conversion through the instance's own frontend (#167).

ComfyUI has no conversion route, so the relay drives a headless Chromium
against the frontend that COMFYUI_URL serves, loads the UI graph with
`app.loadGraphData(wf, true, false, null)` and returns
`(await app.graphToPrompt()).output`, through JSON as the editor's Export (API)
writes it. It is the editor's own conversion, so there is no fallback
converter (D5): a failure is `conversion_unavailable` (no browser, no
frontend, or conversion is off) or `conversion_failed` (the frontend threw),
with the reason.

On when COMFYUI_MCP_CONVERT=1, which the mcp-convert image sets. It needs the
`convert` extra (Playwright) and Chromium's headless shell, which only that
image installs (dockerfile.comfy.relay, RELAY_CONVERT=1).

LOCKDOWN (D3). Three layers, each enforced here and tested live
(tests/test_relay_convert_live.py):

1. Requests. A context-wide route lets a request through only when it is a
   GET to the COMFYUI_URL origin whose path is on ALLOWED_PATHS or under
   ALLOWED_PREFIXES; everything else is aborted (fail closed). It sees the
   page's requests, its iframes', popups' and dedicated workers'. One kind of
   refused request is answered rather than aborted: a POST of the frontend's
   own settings (/api/settings), which it makes as it starts and without
   which it stops loading. It gets an empty 200 from the browser itself and
   never reaches ComfyUI. Every page websocket is closed before it connects
   (route_web_socket).
2. Page APIs. An init script, run before any page script in every frame,
   removes SharedWorker, RTCPeerConnection, RTCDataChannel and WebTransport,
   and makes navigator.sendBeacon refuse. Dedicated workers stay: the
   frontend starts two from blob: URLs as it loads (frontend 1.53.6), so it
   can't run without them. Their HTTP requests meet layer 1; route_web_socket
   doesn't see their websockets, which layer 3 stops.
3. The network. Chromium sends everything but http(s)://<ComfyUI host:port>
   to a proxy that can't be reached (its name never resolves), so websockets
   (ws:// to ComfyUI included), preconnects and anything layer 1 or 2 missed
   go nowhere; its resolver answers NOTFOUND for every name but ComfyUI's, so
   DNS prefetch and preconnect send no lookup; WebRTC may not use UDP outside
   a proxy, and QUIC is off.

The page never queues a prompt (layer 1 refuses every POST), so no
`extra_data` and no credentials reach ComfyUI from here. A COMFYUI_URL that
carries credentials is refused, so they never reach the browser.

What stays reachable: the GET routes on the allowlist, which only read. Under
/extensions/ that includes custom-node JavaScript, which runs in the page with
the same limits; a custom node whose graphs need its own GET routes won't
convert. Chromium runs without its sandbox (Docker's default seccomp profile
and no-new-privileges leave it no usable one), in the relay's container.

LIFECYCLE. One browser per relay, launched on first use and reused. It holds
`pages` tabs, each with the frontend loaded; a conversion takes one, so at
most `pages` run at once and the rest wait. Each tab is its own browser
context, with storage of its own: the frontend saves the open workflow to
storage, and a tab that shared it would restore the last tab's workflow as it
loaded, over the one it was asked to convert (seen on every recycled tab's
first conversion before tabs were separated). The frontend keeps every graph it
loads (about 5 MB a conversion), so a tab is replaced after RECYCLE_AFTER
conversions, the first ones staggered so they don't all reload together, and
after any failure. The Playwright driver grows too, and tab recycling doesn't
reset it, so after RESTART_AFTER conversions the browser and driver are
retired once their conversions finish, and started again. A launch that fails
backs off (LAUNCH_BACKOFF_SECONDS, doubling to LAUNCH_BACKOFF_MAX_SECONDS)
rather than costing every call a fresh attempt. close() stops it all, within
CLOSE_SECONDS, as the server shuts down.
"""

from __future__ import annotations

import asyncio
import collections
import importlib.util
import logging
import re
from typing import Any
from urllib.parse import urlsplit

from .errors import RelayError
from .settings import CONVERT_ENV, MAX_CONVERT_PAGES, redact_url

log = logging.getLogger("comfyrelay.convert")

RECYCLE_AFTER = 25
RESTART_AFTER = 500
LAUNCH_BACKOFF_SECONDS = 5.0
LAUNCH_BACKOFF_MAX_SECONDS = 300.0
PAGE_LOAD_SECONDS = 30.0
CONVERT_SECONDS = 30.0
# How long a conversion waits for a free tab.
TAB_WAIT_SECONDS = 60.0
CLOSE_SECONDS = 2.0

# What the frontend GETs from ComfyUI to load and convert, relative to COMFYUI_URL's path: every path it asked
# for while converting each of the 578 templates ComfyUI v0.38.0 serves (frontend 1.53.6), on a ComfyUI a browser
# had opened before and on one none had, and nothing else. Every one of these routes only reads. Anything else is
# refused, including two it asks for and doesn't need: on a ComfyUI no browser has opened, its first-run template
# browser reads /api/workflow_templates and then every template's thumbnail under /templates/, which cost about
# 250 MB a tab and change no conversion.
ALLOWED_PATHS = frozenset(
    {
        "/",
        "/user.css",
        "/materialdesignicons.min.css",
        "/api/experiment/models",
        "/api/extensions",
        "/api/features",
        "/api/global_subgraphs",
        "/api/i18n",
        "/api/jobs",
        "/api/object_info",
        "/api/settings",
        "/api/system_stats",
        "/api/userdata",
        "/api/users",
        "/api/view",  # the preview of a loader's input file
        "/internal/folder_paths",
    }
)
ALLOWED_PREFIXES = (
    "/assets/",
    "/fonts/",
    "/api/global_subgraphs/",
    "/api/userdata/",
    # Custom-node frontend extensions (none on a bare ComfyUI). A custom node's widgets can change what
    # graphToPrompt writes, so its JavaScript has to load for its graphs to convert as the editor would.
    "/extensions/",
)

LAUNCH_ARGS = [
    "--disable-dev-shm-usage",
    # Request interception sees neither WebRTC nor QUIC. Without a proxy, WebRTC may use no UDP at all, and
    # with QUIC off a WebTransport has nothing to run on (#167: a page's RTCPeerConnection sent STUN to any
    # host before this flag).
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--disable-quic",
]
# Every request the bypass rule below doesn't cover goes here, and the name never resolves (the resolver rule
# maps every name but ComfyUI's to NOTFOUND), so nothing it is sent leaves the container.
DEAD_PROXY = "http://proxy.invalid:9"

# Before any page script, in every frame. Dedicated workers stay (see the module docstring).
INIT_SCRIPT = """(() => {
  const gone = (o, k) => {
    try { Object.defineProperty(o, k, {value: undefined, writable: false, configurable: false}); } catch (e) {}
  };
  for (const k of ['SharedWorker', 'RTCPeerConnection', 'webkitRTCPeerConnection', 'RTCDataChannel',
                   'WebTransport']) gone(globalThis, k);
  try {
    Object.defineProperty(Navigator.prototype, 'sendBeacon',
                          {value: () => false, writable: false, configurable: false});
  } catch (e) {}
})();"""
_READY = "() => !!(window.app && window.app.graphToPrompt && window.app.loadGraphData && window.app.vueAppReady)"
# Through JSON, as the editor's Export (API) writes it: a key whose value is undefined (class_type of a node
# type this instance lacks) is dropped, where Playwright would hand it over as null.
_CONVERT = """async (wf) => {
  await window.app.loadGraphData(wf, true, false, null);
  return JSON.parse(JSON.stringify((await window.app.graphToPrompt()).output));
}"""
_DEFAULT_PORTS = {"http": 80, "https": 443}


def is_ui_format(graph: Any) -> bool:
    """The test workflow.shape_problems uses to refuse a UI-format graph."""
    return isinstance(graph, dict) and isinstance(graph.get("nodes"), list) and "links" in graph


def installed() -> bool:
    return importlib.util.find_spec("playwright") is not None


def off_reason() -> str:
    """Why this server doesn't convert when no Converter was made."""
    if not installed():
        return "this image has no browser to convert with; the mcp-convert image has one"
    return f"{CONVERT_ENV} is not 1 on this server"


def unavailable(reason: str, *, retryable: bool = False, **detail: Any) -> RelayError:
    return RelayError(
        "conversion_unavailable",
        f"UI-to-API conversion is unavailable: {reason}. Nothing was converted; there is no fallback converter.",
        retryable=retryable,
        **detail,
    )


def failed(reason: str, **detail: Any) -> RelayError:
    return RelayError(
        "conversion_failed",
        f"this instance's frontend could not convert the workflow: {reason}. There is no fallback converter.",
        retryable=False,
        **detail,
    )


def _origin(url: str) -> tuple[str, str, int] | None:
    try:
        parts = urlsplit(url)
        port = parts.port or _DEFAULT_PORTS.get(parts.scheme)
    except ValueError:
        return None
    if parts.scheme not in _DEFAULT_PORTS or not parts.hostname or port is None:
        return None
    return parts.scheme, parts.hostname.lower(), port


def _why(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc).splitlines()[0][:300] if str(exc) else ''}"


class _Tab:
    """One slot of the pool: a page with the frontend loaded, in a context of its own, or None until one is."""

    __slots__ = ("limit", "page", "uses")

    def __init__(self, limit: int) -> None:
        self.page: Any = None
        self.uses = 0
        self.limit = limit


class _Session:
    """One launched browser and its driver, with the tabs that convert in it."""

    def __init__(self, pw: Any, browser: Any) -> None:
        self.pw, self.browser = pw, browser
        self.idle: asyncio.Queue[_Tab] = asyncio.Queue()
        self.busy = 0
        self.served = 0
        self.retiring = False
        self.drained = asyncio.Event()
        self.drained.set()
        self.tasks: set[asyncio.Task[Any]] = set()

    def spawn(self, coro: Any) -> None:
        task = asyncio.ensure_future(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def close(self) -> None:
        for task in list(self.tasks):
            task.cancel()
        for closing in (self.browser.close, self.pw.stop):
            try:
                await asyncio.wait_for(closing(), CLOSE_SECONDS)
            except Exception:  # already gone, or slow: the process exit takes the rest
                pass


class Converter:
    def __init__(self, comfyui_url: str, *, pages: int = 2) -> None:
        self.url = comfyui_url
        self.pages = max(1, min(pages, MAX_CONVERT_PAGES))
        self.origin = _origin(comfyui_url)
        parts = urlsplit(comfyui_url)
        self.base = parts.path.rstrip("/")
        self.refused: str | None = None
        if parts.username or parts.password:
            self.refused = "COMFYUI_URL carries credentials, and the converter never hands them to a browser"
        elif self.origin is None:
            self.refused = f"COMFYUI_URL {redact_url(comfyui_url)!r} has no http(s) origin"
        elif not installed():
            self.refused = off_reason()
        # What the lockdown stopped, newest last: (method, or "WS", url). The live test reads it.
        self.blocked: collections.deque[tuple[str, str]] = collections.deque(maxlen=200)
        self.conversions = 0
        self._lock = asyncio.Lock()
        self._session: _Session | None = None
        self._closed = False
        self._failures = 0
        self._retry_at = 0.0
        self._last_error: str | None = None
        self._retiring: set[asyncio.Task[Any]] = set()

    # -- lockdown (D3) --------------------------------------------------------

    def allowed(self, method: str, url: str) -> bool:
        """Layer 1: a GET to the COMFYUI_URL origin, for a path on the allowlist. Anything else is refused."""
        if method != "GET" or self.origin is None or _origin(url) != self.origin:
            return False
        path = urlsplit(url).path
        # Nothing that could step out of an allowed prefix once ComfyUI decodes it.
        if ".." in path or "\\" in path or "%2e" in path.lower() or "%5c" in path.lower():
            return False
        if self.base:
            if path != self.base and not path.startswith(self.base + "/"):
                return False
            path = path[len(self.base) :] or "/"
        return path in ALLOWED_PATHS or path.startswith(ALLOWED_PREFIXES)

    def settings_write(self, method: str, url: str) -> bool:
        """A write of the frontend's own settings to ComfyUI. Refused like every other write, but answered: the
        frontend stores a setting as it starts (Comfy.InstalledVersion, on a ComfyUI no browser has opened yet)
        and stops loading if that fails."""
        if method != "POST" or self.origin is None or _origin(url) != self.origin:
            return False
        path = urlsplit(url).path
        if self.base:
            path = path.removeprefix(self.base)
        return path == "/api/settings" or (path.startswith("/api/settings/") and ".." not in path)

    async def _gate(self, route: Any, request: Any) -> None:
        if self.allowed(request.method, request.url):
            await route.continue_()
            return
        self.blocked.append((request.method, request.url))
        log.debug("blocked %s %s", request.method, request.url)
        if self.settings_write(request.method, request.url):
            await route.fulfill(status=200, body="")  # answered here; ComfyUI never sees it
        else:
            await route.abort("blockedbyclient")

    async def _gate_ws(self, ws: Any) -> None:
        # Not calling connect_to_server means the socket never reaches its server.
        self.blocked.append(("WS", ws.url))
        await ws.close()

    def _launch_options(self) -> dict[str, Any]:
        assert self.origin is not None
        scheme, host, port = self.origin
        return {
            "headless": True,
            "args": [*LAUNCH_ARGS, f"--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE {host}"],
            # <-loopback> first: Chromium never proxies loopback unless told to, and the last rule that
            # matches wins, so ComfyUI's own http(s) origin is the one thing that goes direct. Its ws:// does
            # not match an http:// rule, so websockets to ComfyUI hit the dead proxy too.
            "proxy": {"server": DEAD_PROXY, "bypass": f"<-loopback>,{scheme}://{host}:{port}"},
        }

    # -- lifecycle -------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """For server_info: whether conversion works right now, and if not, why."""
        loop_time = asyncio.get_running_loop().time()
        if self.refused:
            state, reason = "unavailable", self.refused
        elif self._closed:
            state, reason = "stopped", "the server is stopping"
        elif loop_time < self._retry_at:
            state, reason = "backing_off", f"the browser did not start ({self._last_error})"
        elif self._session is None:
            state, reason = "ready", "the browser starts on the first conversion (about 5 s)"
        else:
            state, reason = "running", None
        info: dict[str, Any] = {"state": state, "pages": self.pages, "conversions": self.conversions}
        if reason:
            info["reason"] = reason
        if state == "backing_off":
            info["retry_in_seconds"] = round(self._retry_at - loop_time, 1)
        return info

    async def _browser(self) -> tuple[Any, Any]:
        """Playwright's driver, and a browser launched with the network lockdown (layer 3)."""
        from playwright.async_api import async_playwright

        pw = await async_playwright().start()
        try:
            browser = await pw.chromium.launch(**self._launch_options())
        except BaseException:
            try:
                await asyncio.wait_for(pw.stop(), CLOSE_SECONDS)
            except Exception:
                pass
            raise
        return pw, browser

    async def _launch(self) -> _Session:
        session = _Session(*await self._browser())
        step = RECYCLE_AFTER // self.pages
        for i in range(self.pages):
            # Staggered first limits, so the tabs don't all reload at once.
            session.spawn(self._fill(session, _Tab(RECYCLE_AFTER - i * step)))
        return session

    async def _ready(self) -> _Session:
        """The browser to convert in: the running one, or one launched now (unless a launch is backing off)."""
        async with self._lock:
            if self._closed:
                raise unavailable("the server is stopping", retryable=True)
            session = self._session
            if session is not None and (session.retiring or not session.browser.is_connected()):
                if session.retiring:
                    await session.drained.wait()
                else:
                    log.warning("the converter's browser went away; starting another")
                self._session = None
                await session.close()
                session = None
            if session is None:
                loop = asyncio.get_running_loop()
                if loop.time() < self._retry_at:
                    raise unavailable(
                        f"the browser did not start ({self._last_error}); the next attempt is in "
                        f"{self._retry_at - loop.time():.0f}s",
                        retryable=True,
                    )
                try:
                    session = await self._launch()
                except Exception as exc:
                    self._failures += 1
                    delay = min(LAUNCH_BACKOFF_MAX_SECONDS, LAUNCH_BACKOFF_SECONDS * 2 ** (self._failures - 1))
                    self._retry_at = loop.time() + delay
                    self._last_error = _why(exc)
                    log.warning("the converter's browser did not start (%s); next attempt in %.0fs", _why(exc), delay)
                    raise unavailable(
                        f"the browser did not start ({self._last_error}); the next attempt is in {delay:.0f}s",
                        retryable=True,
                    ) from None
                if self._closed:  # close() ran while it launched
                    await session.close()
                    raise unavailable("the server is stopping", retryable=True)
                self._failures = 0
                self._last_error = None
                self._session = session
            return session

    async def _open(self, session: _Session) -> Any:
        """A page with the frontend loaded, in a new context with the request and page-API lockdown (layers 1, 2)."""
        context = await session.browser.new_context(service_workers="block", accept_downloads=False)
        try:
            await context.add_init_script(INIT_SCRIPT)
            await context.route("**/*", self._gate)
            await context.route_web_socket(re.compile(r".*"), self._gate_ws)
            page = await context.new_page()
        except BaseException:
            await _close_page_and_context(context)
            raise
        try:
            await page.goto(self.url, wait_until="load", timeout=PAGE_LOAD_SECONDS * 1000)
            await page.wait_for_function(_READY, polling=250, timeout=PAGE_LOAD_SECONDS * 1000)
        except BaseException:
            await _close_page_and_context(context)
            raise
        return page

    async def _fill(self, session: _Session, tab: _Tab, old: Any = None) -> None:
        """Give `tab` a fresh page (closing `old` first) and put it back in the pool. A tab that fails to load
        goes back empty, and the conversion that takes it tries again."""
        try:
            if old is not None:
                await _close_page_and_context(old.context)
            if not session.retiring:
                tab.page = await self._open(session)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("a converter tab did not load the frontend: %s", _why(exc))
        finally:
            session.idle.put_nowait(tab)

    async def _retire(self, session: _Session) -> None:
        try:
            await self._ready()  # waits for its conversions to finish, closes it, launches the next
        except RelayError as exc:
            if not self._closed:
                log.warning("the converter's browser did not restart: %s", exc.message)

    async def close(self) -> None:
        """Stop the browser and its driver. The server calls it as it shuts down; nothing converts after."""
        self._closed = True
        for task in list(self._retiring):
            task.cancel()
        session, self._session = self._session, None
        if session is not None:
            await session.close()

    # -- conversion ------------------------------------------------------------

    async def convert(self, workflow: dict[str, Any]) -> dict[str, Any]:
        """The API graph this instance's frontend makes of `workflow`, or RelayError conversion_unavailable or
        conversion_failed."""
        if self.refused:
            raise unavailable(self.refused)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + TAB_WAIT_SECONDS
        while True:
            session = await self._ready()
            try:
                tab = await asyncio.wait_for(session.idle.get(), max(0.0, deadline - loop.time()))
            except TimeoutError:
                raise unavailable(
                    f"every converter tab stayed busy for {TAB_WAIT_SECONDS:.0f}s", retryable=True
                ) from None
            if not session.retiring and session is self._session:
                break
            session.idle.put_nowait(tab)  # a retiring browser takes no new work; _ready replaces it
        session.busy += 1
        session.drained.clear()
        converted = False
        try:
            if tab.page is None:
                try:
                    tab.page = await self._open(session)
                except Exception as exc:
                    raise unavailable(
                        f"this instance's frontend did not load at {redact_url(self.url)} ({_why(exc)})",
                        retryable=True,
                    ) from None
            tab.uses += 1
            session.served += 1
            self.conversions += 1
            try:
                output = await asyncio.wait_for(tab.page.evaluate(_CONVERT, workflow), CONVERT_SECONDS)
            except TimeoutError:
                raise failed(f"no answer in {CONVERT_SECONDS:.0f}s") from None
            except Exception as exc:
                raise failed(_why(exc)) from None
            if not isinstance(output, dict):
                raise failed(f"graphToPrompt returned {type(output).__name__}, not an object")
            converted = True
            return output
        finally:
            session.busy -= 1
            self._release(session, tab, converted)
            if session.busy == 0:
                session.drained.set()

    def _release(self, session: _Session, tab: _Tab, converted: bool) -> None:
        if tab.page is None or (converted and tab.uses < tab.limit):
            session.idle.put_nowait(tab)
        else:  # used up, or failed: a frontend left in a bad state is not reused
            old, tab.page, tab.uses, tab.limit = tab.page, None, 0, RECYCLE_AFTER
            session.spawn(self._fill(session, tab, old))
        if session.served >= RESTART_AFTER and not session.retiring:
            session.retiring = True
            log.info("restarting the converter's browser after %d conversions", session.served)
            task = asyncio.ensure_future(self._retire(session))
            self._retiring.add(task)
            task.add_done_callback(self._retiring.discard)


async def _close_page_and_context(context: Any) -> None:
    try:
        await asyncio.wait_for(context.close(), CLOSE_SECONDS)
    except Exception:
        pass
