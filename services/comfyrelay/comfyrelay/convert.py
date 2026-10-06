"""UI-to-API workflow conversion through the instance's own frontend (#167).

ComfyUI has no conversion route, so the relay drives a headless Chromium
against the frontend that COMFYUI_URL serves, loads the UI graph with
`app.loadGraphData(wf, true, false, null)`, lets the previews it starts
settle, and returns `(await app.graphToPrompt()).output`, through JSON as the
editor's Export (API) writes it. It is the editor's own conversion, so there is no fallback
converter (D5): a failure is `conversion_unavailable` (no browser, no
frontend, or conversion is off) or `conversion_failed` (the frontend threw),
with the reason.

On when COMFYUI_MCP_CONVERT=1, which the mcp-convert image sets. It needs the
`convert` extra (Playwright) and Chromium's headless shell, which only that
image installs (dockerfile.comfy.relay, RELAY_CONVERT=1).

LOCKDOWN (D3). The browser has no network: Chromium sends every request,
ComfyUI's included, to a proxy whose name never resolves. The only way
anything reaches ComfyUI is the relay's own Python, which fetches what the
route below allows and hands the answer to the page. Each layer is enforced
here and tested live (tests/test_relay_convert_live.py), where the ComfyUI
the converter talks to is a recording stand-in that checks every request it
receives was an allowlisted GET:

1. Requests. A route on each tab's context takes every request it sees. A GET
   to the COMFYUI_URL origin for a path on ALLOWED_PATHS or under
   ALLOWED_PREFIXES is fetched by the relay and fulfilled with ComfyUI's
   answer; everything else is aborted (fail closed). The relay's fetch is that
   GET at a URL it rebuilds from COMFYUI_URL and the checked path, with a few
   request headers, no body, no cookies kept, no redirect followed. It streams
   the answer and gives up on one over MAX_FETCH_BYTES (the page gets an
   abort), and runs at most FETCH_CONCURRENCY at once, of which only one may
   hold more than LARGE_FETCH_BYTES, so what it buffers stays bounded. A
   ranged request (a video preview's) is passed on with its range cut to
   RANGE_BYTES, so a large input video is read a few MiB at a time, as the
   browser asks for it, never whole. One refused request is answered
   rather than aborted: a POST of the frontend's own settings (/api/settings),
   which it makes as it starts and without which it stops loading. It gets an
   empty 200 from the route and never reaches ComfyUI. Every page websocket is
   closed before it connects (route_web_socket).
2. Page APIs. An init script, run before any page script in every frame
   (about:blank and srcdoc iframes included), removes SharedWorker,
   RTCPeerConnection, RTCDataChannel and WebTransport, and makes
   navigator.sendBeacon refuse. Dedicated workers stay: the frontend starts
   two from blob: URLs as it loads (frontend 1.53.6), so it can't run without
   them.
3. The network. What the route doesn't see goes to the dead proxy:
   websockets from workers, speculation-rules prefetch and prerender (both
   measured getting past a route that let ComfyUI's origin go direct), and
   preconnects. The resolver answers NOTFOUND for every name, so a DNS
   prefetch sends no lookup; WebRTC may not use UDP outside a proxy, and QUIC
   is off.

The relay sends ComfyUI only GETs on the allowlist, so no write, no
`extra_data` and no credentials reach ComfyUI from here. A COMFYUI_URL that
carries credentials is refused for conversion.

What stays reachable: the GET routes on the allowlist, as ComfyUI implements
them. Query strings aren't checked, so a parameter like /api/userdata's dir is
left to ComfyUI's own path checks. /api/view serves input files for the
editor's previews, and it has to: once a video's preview has loaded, LoadVideo
exports a `video-preview` input it lacks otherwise. Under /extensions/ any GET a custom node
registers there is reachable, and custom-node JavaScript runs in the page
under the same limits; a custom node whose graphs need its own GET routes
elsewhere won't convert. "Only reads" was checked against a bare ComfyUI
v0.38.0's handlers. Chromium runs without its sandbox (Docker's default
seccomp profile and no-new-privileges leave it no usable one), in the relay's
container.

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
import os
import re
import weakref
from http.cookiejar import CookieJar, DefaultCookiePolicy
from typing import Any
from urllib.parse import unquote, urlsplit

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
# refused, including what it asks for and doesn't need: on a ComfyUI no browser has opened, its first-run template
# browser reads /api/workflow_templates and then every template's thumbnail under /templates/, about 250 MB a tab.
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
        # A loader's input file, for its preview. Needed: once a video's preview has loaded, LoadVideo exports a
        # `video-preview` input (62 templates differ without it). Large videos come in ranges (RANGE_BYTES).
        "/api/view",
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
# Every request the browser itself makes goes here, and the name never resolves (the resolver rule maps every name
# to NOTFOUND), so nothing it is sent leaves the container. Loopback too: Chromium never proxies it unless told.
DEAD_PROXY = "http://proxy.invalid:9"
NO_BYPASS = "<-loopback>"
# What the relay passes on from the page's request to ComfyUI, and what it drops from ComfyUI's answer (httpx2
# hands over the body decoded and whole).
FORWARD_HEADERS = frozenset({"accept", "accept-language", "comfy-user", "if-none-match", "if-modified-since"})
DROP_HEADERS = frozenset(
    {"content-encoding", "content-length", "transfer-encoding", "connection", "keep-alive", "set-cookie"}
)
# The relay's fetches for the tabs hold each answer in memory until the page has it, so they are bounded: an answer
# over MAX_FETCH_BYTES is refused (the largest the frontend reads on a bare ComfyUI v0.38.0 is /api/object_info,
# about 2 MB; a frontend bundle is under 5 MB), at most FETCH_CONCURRENCY run at once, and only one of those may
# hold more than LARGE_FETCH_BYTES.
MAX_FETCH_BYTES = 32 * 1024 * 1024
LARGE_FETCH_BYTES = 4 * 1024 * 1024
FETCH_CONCURRENCY = 6
# The most of a file one ranged request (a video preview's: `Range: bytes=0-`) reads. The browser asks for the next
# range when it needs it, so a video of any size is read in pieces this big, and only as far as the preview goes.
RANGE_BYTES = 4 * 1024 * 1024
# All the browser's environment: nothing of the relay's own (COMFYUI_MCP_HTTP_TOKEN above all) reaches it.
BROWSER_ENV = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "TZ", "FONTCONFIG_FILE", "FONTCONFIG_PATH")

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
_FRONTEND_VERSION = "() => window.__COMFYUI_FRONTEND_VERSION__ || null"
# Through JSON, as the editor's Export (API) writes it: a key whose value is undefined (class_type of a node
# type this instance lacks) is dropped, where Playwright would hand it over as null. _CONVERT is the two in one, as
# a person would run them, for the tests' oracle.
_LOAD = "async (wf) => { await window.app.loadGraphData(wf, true, false, null); }"
_EXPORT = "async () => JSON.parse(JSON.stringify((await window.app.graphToPrompt()).output))"
_CONVERT = """async (wf) => {
  await window.app.loadGraphData(wf, true, false, null);
  return JSON.parse(JSON.stringify((await window.app.graphToPrompt()).output));
}"""
# What graphToPrompt writes can depend on a preview having loaded: a LoadVideo adds its `video-preview` input only
# once its video has (frontend 1.53.6 waits up to 8.2 s for it, then retries once). So between loading a graph and
# exporting it, the relay waits until the tab's fetches have been quiet for SETTLE_QUIET_SECONDS, at most
# SETTLE_MAX_SECONDS. A graph with nothing to preview has nothing in flight, and waits for nothing.
SETTLE_QUIET_SECONDS = 0.3
SETTLE_MAX_SECONDS = 10.0
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


def _gone(exc: BaseException, page: Any, browser: Any, crashed: Any) -> bool:
    """Whether a failed evaluate means the tab or the browser went away (a crashed renderer, a closed target, a
    killed browser) rather than the frontend rejecting the graph. Judged by what Playwright knows, never by the
    error's text, which the frontend's own errors could match."""
    if type(exc).__name__ == "TargetClosedError" or page in crashed:
        return True
    try:
        return page.is_closed() or not browser.is_connected()
    except Exception:
        return True


class _Activity:
    """A tab's fetches through the relay: the paths in flight, and when the last one started or ended."""

    __slots__ = ("changed", "inflight")

    def __init__(self) -> None:
        self.inflight: collections.Counter[str] = collections.Counter()
        self.changed = 0.0

    def start(self, path: str) -> None:
        self.inflight[path] += 1
        self.changed = asyncio.get_running_loop().time()

    def end(self, path: str) -> None:
        self.inflight[path] -= 1
        if self.inflight[path] <= 0:
            del self.inflight[path]
        self.changed = asyncio.get_running_loop().time()

    async def settle(self) -> bool:
        """Wait until nothing has been in flight for SETTLE_QUIET_SECONDS, counted from the later of the last
        change and this call (so a preview whose fetch starts just after the graph loaded is still waited for), at
        most SETTLE_MAX_SECONDS. False when the cap ran out first."""
        loop = asyncio.get_running_loop()
        began = loop.time()
        deadline = began + SETTLE_MAX_SECONDS
        while loop.time() < deadline:
            if not self.inflight and loop.time() - max(self.changed, began) >= SETTLE_QUIET_SECONDS:
                return True
            await asyncio.sleep(0.05)
        return False


class _TooLarge(Exception):
    """An answer over MAX_FETCH_BYTES: the relay stops reading it, and the page gets an abort."""


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
        # What the relay's fetches are built on: COMFYUI_URL's scheme, host and port, and its path.
        self.root = f"{parts.scheme}://{parts.netloc}{self.base}"
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
        # The frontend version the tabs loaded, once one has (window.__COMFYUI_FRONTEND_VERSION__).
        self.frontend_version: str | None = None
        self._http: Any = None
        self._fetches = asyncio.Semaphore(FETCH_CONCURRENCY)
        self._large = asyncio.Lock()
        self._crashed: weakref.WeakSet[Any] = weakref.WeakSet()  # tabs whose renderer crashed
        self._activity: weakref.WeakKeyDictionary[Any, _Activity] = weakref.WeakKeyDictionary()
        self._lock = asyncio.Lock()
        self._session: _Session | None = None
        self._closed = False
        self._failures = 0
        self._retry_at = 0.0
        self._last_error: str | None = None
        self._retiring: set[asyncio.Task[Any]] = set()

    # -- lockdown (D3) --------------------------------------------------------

    def _paths(self, url: str) -> tuple[str, str] | None:
        """`url`'s path relative to COMFYUI_URL's, decoded (to match the allowlist) and as sent (to rebuild the
        fetch), or None when it isn't on the COMFYUI_URL origin under its path, or could step out of where it
        points: a `%25` (an encoded `%`, so a second decode, which some ComfyUI routes do, decodes again), or a
        `.` or `..` segment or a backslash once decoded once or twice."""
        if self.origin is None or _origin(url) != self.origin:
            return None
        raw = urlsplit(url).path
        if "%25" in raw:
            return None
        if self.base:
            if raw != self.base and not raw.startswith(self.base + "/"):
                return None
            raw = raw[len(self.base) :] or "/"
        once = unquote(raw)
        for decoded in (once, unquote(once)):
            if "\\" in decoded or any(segment in (".", "..") for segment in decoded.split("/")):
                return None
        return once, raw

    def _path(self, url: str) -> str | None:
        paths = self._paths(url)
        return paths[0] if paths else None

    def allowed(self, method: str, url: str) -> bool:
        """Layer 1: a GET to the COMFYUI_URL origin, for a path on the allowlist. Anything else is refused."""
        path = self._path(url) if method == "GET" else None
        return path is not None and (path in ALLOWED_PATHS or path.startswith(ALLOWED_PREFIXES))

    def fetch_url(self, url: str) -> str:
        """The URL the relay fetches for an allowed `url`: rebuilt from COMFYUI_URL and the checked path, with the
        query as sent and no fragment, so nothing else of the page's URL reaches ComfyUI."""
        paths = self._paths(url)
        assert paths is not None
        query = urlsplit(url).query
        return f"{self.root}{paths[1]}" + (f"?{query}" if query else "")

    def settings_write(self, method: str, url: str) -> bool:
        """A write of the frontend's own settings to ComfyUI. Refused like every other write, but answered: the
        frontend stores a setting as it starts (Comfy.InstalledVersion, on a ComfyUI no browser has opened yet)
        and stops loading if that fails."""
        path = self._path(url) if method == "POST" else None
        return path is not None and (path == "/api/settings" or path.startswith("/api/settings/"))

    async def _gate(self, route: Any, request: Any, activity: _Activity | None = None) -> None:
        if self.allowed(request.method, request.url):
            path = urlsplit(request.url).path
            if activity is not None:
                activity.start(path)
            try:
                await self._relay(route, request)
            finally:
                if activity is not None:
                    activity.end(path)
            return
        self.blocked.append((request.method, request.url))
        log.debug("blocked %s %s", request.method, request.url)
        if self.settings_write(request.method, request.url):
            await _quietly(route.fulfill(status=200, body=""))  # answered here; ComfyUI never sees it
        else:
            await _quietly(route.abort("blockedbyclient"))

    async def _relay(self, route: Any, request: Any) -> None:
        """Fetch an allowed request for the page, within the fetch limits, and hand it the answer."""
        async with self._fetches:
            large = False
            try:
                answer, large = await self._fetch(request)
                await _quietly(route.fulfill(**answer))
            except _TooLarge:
                self.blocked.append((request.method, request.url))
                log.warning("refused %s for a converter tab: over %d bytes", request.url, MAX_FETCH_BYTES)
                await _quietly(route.abort("failed"))
            except Exception as exc:  # ComfyUI unreachable, or the tab closed meanwhile
                log.debug("could not fetch %s for a converter tab: %s", request.url, _why(exc))
                await _quietly(route.abort("failed"))
            finally:
                if large:
                    self._large.release()

    async def _fetch(self, request: Any) -> tuple[dict[str, Any], bool]:
        """The one way a converter tab reaches ComfyUI: the relay GETs the allowed URL itself, streaming the answer
        and giving up past MAX_FETCH_BYTES. Returns the answer for route.fulfill, and whether it took the one slot
        for a large answer, which the caller releases once the page has it."""
        if self._http is None:
            self._http = _client()
        headers = {k: v for k, v in request.headers.items() if k.lower() in FORWARD_HEADERS}
        wanted = next((v for k, v in request.headers.items() if k.lower() == "range"), None)
        ranged = self._range(wanted) if wanted else None
        if ranged:
            headers["range"] = ranged
        large = False
        try:
            async with self._http.stream("GET", self.fetch_url(request.url), headers=headers) as answer:
                declared = answer.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > MAX_FETCH_BYTES:
                    raise _TooLarge
                body = bytearray()
                async for chunk in answer.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_FETCH_BYTES:
                        raise _TooLarge
                    if not large and len(body) > LARGE_FETCH_BYTES:
                        await self._large.acquire()
                        large = True
                status = answer.status_code
                kept = {k: v for k, v in answer.headers.items() if k.lower() not in DROP_HEADERS}
        except BaseException:
            if large:
                self._large.release()
            raise
        return {"status": status, "headers": kept, "body": bytes(body)}, large

    async def _gate_ws(self, ws: Any) -> None:
        # Not calling connect_to_server means the socket never reaches its server.
        self.blocked.append(("WS", ws.url))
        await ws.close()

    @staticmethod
    def _range(value: str) -> str | None:
        """A page's Range header, cut to at most RANGE_BYTES; None (send no Range) for one it can't read."""
        start_end = re.fullmatch(r"bytes=(\d+)-(\d*)", value.strip())
        if start_end:
            start = int(start_end[1])
            end = start + RANGE_BYTES - 1
            if start_end[2]:
                end = min(end, int(start_end[2]))
            return f"bytes={start}-{end}"
        suffix = re.fullmatch(r"bytes=-(\d+)", value.strip())
        return f"bytes=-{min(int(suffix[1]), RANGE_BYTES)}" if suffix else None

    def _launch_options(self) -> dict[str, Any]:
        # No bypass: the browser reaches nothing, ComfyUI included. The route fetches what it allows.
        return {
            "headless": True,
            "args": [*LAUNCH_ARGS, "--host-resolver-rules=MAP * ~NOTFOUND"],
            "proxy": {"server": DEAD_PROXY, "bypass": NO_BYPASS},
            "env": {name: os.environ[name] for name in BROWSER_ENV if name in os.environ},
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
        if self.frontend_version:
            info["frontend_version"] = self.frontend_version
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
            activity = _Activity()
            await context.route("**/*", lambda route, request: self._gate(route, request, activity))
            await context.route_web_socket(re.compile(r".*"), self._gate_ws)
            page = await context.new_page()
            page.on("crash", self._crashed.add)
            self._activity[page] = activity
        except BaseException:
            await _close_page_and_context(context)
            raise
        try:
            await page.goto(self.url, wait_until="load", timeout=PAGE_LOAD_SECONDS * 1000)
            await page.wait_for_function(_READY, polling=250, timeout=PAGE_LOAD_SECONDS * 1000)
            version = await page.evaluate(_FRONTEND_VERSION)
        except BaseException:
            await _close_page_and_context(context)
            raise
        if isinstance(version, str):
            self.frontend_version = version[:40]
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
        http, self._http = self._http, None
        if http is not None:
            await _quietly(http.aclose())

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
                output = await asyncio.wait_for(self._evaluate(tab.page, workflow), CONVERT_SECONDS)
            except TimeoutError:
                raise failed(f"no answer in {CONVERT_SECONDS:.0f}s") from None
            except Exception as exc:
                if _gone(exc, tab.page, session.browser, self._crashed):
                    raise unavailable(f"the converter's browser tab went away ({_why(exc)})", retryable=True) from None
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

    async def _evaluate(self, page: Any, workflow: dict[str, Any]) -> Any:
        """Load the graph, let the previews it started settle, and export it."""
        await page.evaluate(_LOAD, workflow)
        activity = self._activity.get(page)
        if activity is not None and not await activity.settle():
            # Exported anyway: a UI-only preview input (LoadVideo's video-preview) may be missing; ComfyUI ignores it.
            log.warning(
                "a converter tab's fetches were still in flight after %.0fs (%d: %s); exported without waiting longer",
                SETTLE_MAX_SECONDS,
                sum(activity.inflight.values()),
                ", ".join(sorted(activity.inflight)[:5]),
            )
        return await page.evaluate(_EXPORT)

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


def _client(**options: Any) -> Any:
    """The relay's client for the tabs' fetches. Its cookie jar accepts nothing, so a cookie ComfyUI sets is never
    sent back, from any tab."""
    import httpx2

    jar = CookieJar(policy=DefaultCookiePolicy(allowed_domains=[]))
    return httpx2.AsyncClient(timeout=PAGE_LOAD_SECONDS, follow_redirects=False, cookies=jar, **options)


async def _quietly(awaitable: Any) -> None:
    """Await a route action whose tab may already be gone."""
    try:
        await awaitable
    except Exception:
        pass


async def _close_page_and_context(context: Any) -> None:
    try:
        await asyncio.wait_for(context.close(), CLOSE_SECONDS)
    except Exception:
        pass
