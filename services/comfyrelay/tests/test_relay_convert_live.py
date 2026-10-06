"""The converter (#167) against a real, booted ComfyUI and a real Chromium: its lockdown (D3), its allowlist, and
its conversions against the frontend's own export (the oracle, D8). Skipped unless COMFYRELAY_LIVE_COMFYUI_URL
names a ComfyUI and Playwright (the `convert` extra) and its Chromium are installed:

    cd services
    uv run --locked --extra convert playwright install --only-shell chromium
    COMFYRELAY_LIVE_COMFYUI_URL=http://127.0.0.1:8188 \\
      uv run --locked --extra convert pytest -q comfyrelay/tests/test_relay_convert_live.py

The lockdown tests point the converter, and a plain browser for the negative control, at a stand-in ComfyUI this
test runs in front of the real one. It records every request it receives, forwards plain GETs to the real ComfyUI,
and answers everything else itself, so nothing here ever writes to ComfyUI. A page script then tries every way out
it can find: POST, PUT and DELETE to ComfyUI and a GET it serves but the frontend doesn't need; GET to another
origin (a canary this test runs) and to api.comfy.org; websockets from the page and from a dedicated worker; a
worker's fetch, and a fetch from a worker a worker started; a SharedWorker, including one taken from a fresh
about:blank or srcdoc iframe; speculation-rules prefetch and prerender; a beacon, a cross-origin iframe, a popup, a
preconnect; WebRTC to a UDP socket this test holds, and WebTransport from a worker. In the plain browser each one
gets out (but the preconnect: the headless shell makes none). In a converter tab none does, and every request
the stand-in received from it was an allowlisted GET. DNS prefetch isn't observable here: the resolver rule keeps
it from sending any lookup by construction.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from comfyrelay import convert as conv
from comfyrelay.errors import RelayError
from relay_helpers import free_port

URL = os.environ.get("COMFYRELAY_LIVE_COMFYUI_URL", "").rstrip("/")
pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not URL, reason="COMFYRELAY_LIVE_COMFYUI_URL is not set"),
    pytest.mark.skipif(importlib.util.find_spec("playwright") is None, reason="the convert extra is not installed"),
]

CANARY_FILE = "convert-lockdown-canary.json"

ESCAPES = """async ([comfy, canary, file, udp, fresh]) => {
  const worker = (src) => new Promise((ok, no) => {
    const w = new Worker(URL.createObjectURL(new Blob([src], {type: 'text/javascript'})));
    w.onmessage = e => e.data.startsWith('ok') ? ok(e.data) : no(new Error(e.data));
    setTimeout(() => no(new Error('timeout')), 5000);
  });
  const ws = (u) => `try { const s = new WebSocket(${JSON.stringify(u)}); s.onopen = () => postMessage('ok open');
    s.onerror = () => postMessage('error'); } catch (e) { postMessage('threw ' + e); }`;
  const post = (tag, say = 'postMessage') => `fetch(${JSON.stringify(comfy)} + '/api/userdata/escape-${tag}.json',
    {method: 'POST', body: '{}'}).then(r => ${say}('ok ' + r.status), e => ${say}('blocked: ' + e))`;
  const sharedFrom = (attrs, tag) => new Promise((ok, no) => {
    const f = document.createElement('iframe'); Object.assign(f, attrs); document.body.appendChild(f);
    setTimeout(() => {
      const SW = f.contentWindow.SharedWorker;
      if (!SW) return no(new Error('no SharedWorker in the iframe'));
      const src = 'onconnect = e => { const p = e.ports[0]; ' + post(tag, 'p.postMessage') + '; };';
      const w = new SW(URL.createObjectURL(new Blob([src], {type: 'text/javascript'})));
      w.port.onmessage = e => e.data.startsWith('ok') ? ok(e.data) : no(new Error(e.data));
      w.port.start();
      setTimeout(() => no(new Error('timeout')), 5000);
    }, 300);
  });
  const tries = {
    post_comfyui: () => fetch(comfy + '/api/userdata/' + file, {method: 'POST', body: '{"leaked": true}'}),
    put_comfyui: () => fetch(comfy + '/api/userdata/' + file, {method: 'PUT', body: '{}'}),
    delete_comfyui: () => fetch(comfy + '/api/userdata/' + file, {method: 'DELETE'}),
    get_comfyui_off_allowlist: () => fetch(comfy + '/api/prompt'),
    get_other_origin: () => fetch(canary + '/fetch'),
    get_api_comfy_org: () => fetch('https://api.comfy.org/'),
    websocket_comfyui: () => new Promise((ok, no) => {
      const s = new WebSocket(comfy.replace(/^http/, 'ws') + '/escape/ws-page');
      s.onopen = () => ok('open');
      s.onerror = () => no(new Error('ws error'));
      s.onclose = () => no(new Error('ws closed'));
      setTimeout(() => no(new Error('ws timeout')), 5000);
    }),
    worker_fetch_other_origin: () => worker(`fetch(${JSON.stringify(canary + '/worker')})
      .then(() => postMessage('ok'), e => postMessage('blocked: ' + e))`),
    worker_websocket_comfyui: () => worker(ws(comfy.replace(/^http/, 'ws') + '/escape/ws-worker')),
    worker_websocket_other_origin: () => worker(ws(canary.replace(/^http/, 'ws') + '/worker-ws')),
    worker_webtransport: () => worker(`try { const t = new WebTransport('https://127.0.0.1:${udp}/');
      t.ready.then(() => postMessage('ok'), e => postMessage('failed ' + e)); }
      catch (e) { postMessage('threw ' + e); }`),
    nested_worker_post_comfyui: () => worker(`const w = new Worker(URL.createObjectURL(
      new Blob([${JSON.stringify(post('nested'))}], {type: 'text/javascript'})));
      w.onmessage = e => postMessage(e.data);`),
    shared_worker: async () => { new SharedWorker(URL.createObjectURL(new Blob([''], {type: 'text/javascript'})));
                                 return 'started'; },
    shared_worker_from_blank_iframe: () => sharedFrom({}, 'shared-blank'),
    shared_worker_from_srcdoc_iframe: () => sharedFrom({srcdoc: '<p>x</p>'}, 'shared-srcdoc'),
    speculation_rules: async () => {
      const s = document.createElement('script'); s.type = 'speculationrules';
      s.textContent = JSON.stringify({prefetch: [{source: 'list', urls: [comfy + '/escape/prefetch']}],
                                      prerender: [{source: 'list', urls: [comfy + '/escape/prerender']}]});
      document.head.appendChild(s);
      return 'inserted';
    },
    beacon_other_origin: async () => {
      if (!navigator.sendBeacon(canary + '/beacon', 'x')) throw new Error('beacon refused');
      return 'queued';
    },
    iframe_other_origin: async () => {
      const f = document.createElement('iframe'); f.src = canary + '/iframe'; document.body.appendChild(f);
      return 'inserted';
    },
    popup_other_origin: async () => { window.open(canary + '/popup'); return 'opened'; },
    preconnect_other_origin: async () => {
      const l = document.createElement('link'); l.rel = 'preconnect'; l.href = fresh; document.head.appendChild(l);
      return 'inserted';
    },
    webrtc_udp: async () => {
      const pc = new RTCPeerConnection({iceServers: [{urls: 'stun:127.0.0.1:' + udp}]});
      pc.createDataChannel('x');
      await pc.setLocalDescription(await pc.createOffer());
      await new Promise(r => setTimeout(r, 2000));
      pc.close();
      return 'gathered';
    },
  };
  const out = {};
  for (const [name, attempt] of Object.entries(tries)) {
    try { const r = await attempt(); out[name] = 'reached: ' + (r && r.status !== undefined ? r.status : r); }
    catch (e) { out[name] = 'blocked: ' + String(e).slice(0, 120); }
  }
  // Let beacons, iframes, popups, preconnects and speculation rules go, or not.
  await new Promise(r => setTimeout(r, 3000));
  return out;
}"""
# Tries whose fate the page can't see (it only inserts or opens something); the stand-in and the canaries can.
ONLY_THE_SERVERS_KNOW = {"iframe_other_origin", "popup_other_origin", "preconnect_other_origin", "speculation_rules"}
# What a plain browser gets to ComfyUI that a converter tab must not: the stand-in records each.
ESCAPED_TO_COMFYUI = {
    ("POST", "/api/userdata/escape-shared-blank.json"),
    ("POST", "/api/userdata/escape-shared-srcdoc.json"),
    ("POST", "/api/userdata/escape-nested.json"),
    ("GET", "/escape/prefetch"),
    ("GET", "/escape/prerender"),
    ("GET", "/api/prompt"),
    ("WS", "/escape/ws-page"),
    ("WS", "/escape/ws-worker"),
}


class StandIn(ThreadingHTTPServer):
    """A ComfyUI the lockdown tests point at: it records (method, path) of every request, "WS" for a websocket
    upgrade, forwards plain GETs to the real ComfyUI so the frontend loads, and answers everything else itself."""

    daemon_threads = True

    def __init__(self, port: int) -> None:
        self.requests: list[tuple[str, str]] = []
        self.sent: dict[str, int] = {}  # bytes of each large body it got out before the client stopped reading
        self.views: list[int] = []  # the size of each /api/view answer
        self.local = threading.local()
        super().__init__(("127.0.0.1", port), _StandInHandler)


class _StandInHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: StandIn

    def handle(self) -> None:
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError):  # a browser closing its connections
            pass

    def _answer(self, status: int, body: bytes, headers: dict[str, str]) -> None:
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _any(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        upgrade = "websocket" in (self.headers.get("Upgrade") or "").lower()
        path = urlsplit(self.path).path
        self.server.requests.append(("WS" if upgrade else self.command, path))
        if self.command != "GET" or upgrade or path.startswith("/escape/"):
            self._answer(200, b"{}", {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"})
            return
        if path.startswith("/assets/large-") or path == "/api/view":
            self._large(path, parse_qs(urlsplit(self.path).query))
            return
        http = getattr(self.server.local, "http", None)
        if http is None:
            http = self.server.local.http = httpx2.Client(timeout=60)
        keep = ("accept", "accept-language", "comfy-user", "range")
        headers = {k: v for k, v in self.headers.items() if k.lower() in keep}
        answer = http.get(URL + self.path, headers={**headers, "accept-encoding": "identity"})
        drop = {"content-length", "content-encoding", "transfer-encoding", "connection", "keep-alive"}
        self._answer(
            answer.status_code, answer.content, {k: v for k, v in answer.headers.items() if k.lower() not in drop}
        )

    def _large(self, path: str, query: dict) -> None:
        """A body of `mb` MB (default 300), as a large input video would be: with a Content-Length, or chunked, or
        for /api/view the range asked for, as ComfyUI serves an input file."""
        size = int(query.get("mb", ["300"])[0]) * 1024 * 1024
        chunked = "chunked" in query
        wanted = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range") or "")
        if path == "/api/view" and wanted:
            start = int(wanted[1])
            end = min(int(wanted[2]) if wanted[2] else size - 1, size - 1)
            self.server.views.append(end - start + 1)
            self.send_response(206)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            try:
                self.wfile.write(b"\0" * (end - start + 1))
            except (ConnectionResetError, BrokenPipeError):
                pass
            return
        if path == "/api/view":
            self.server.views.append(size)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Transfer-Encoding" if chunked else "Content-Length", "chunked" if chunked else str(size))
        self.end_headers()
        block, sent = b"\0" * (1024 * 1024), 0
        key = f"{path}?{urlsplit(self.path).query}"
        try:
            while sent < size:
                self.wfile.write(b"%x\r\n%s\r\n" % (len(block), block) if chunked else block)
                sent += len(block)
                self.server.sent[key] = sent
            if chunked:
                self.wfile.write(b"0\r\n\r\n")
        except (ConnectionResetError, BrokenPipeError):
            pass
        self.close_connection = True

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _any

    def log_message(self, *args: object) -> None:
        pass


class Canary(ThreadingHTTPServer):
    """Records every TCP connection and every request: a preconnect opens a connection and sends nothing."""

    daemon_threads = True

    def __init__(self, port: int) -> None:
        self.connections = 0
        self.requests: list[str] = []
        super().__init__(("127.0.0.1", port), _CanaryHandler)

    def verify_request(self, request, client_address) -> bool:
        self.connections += 1
        return True


class _CanaryHandler(BaseHTTPRequestHandler):
    def _any(self) -> None:
        self.server.requests.append(f"{self.command} {self.path}")
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_POST = do_PUT = do_DELETE = do_OPTIONS = _any

    def log_message(self, *args: object) -> None:
        pass


def _serve(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def standin():
    server = _serve(StandIn(free_port()))
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def canary():
    server = _serve(Canary(free_port()))
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def fresh():
    """A second canary, for the preconnect alone: Chromium preconnects only to an origin it holds no idle
    connection to."""
    server = _serve(Canary(free_port()))
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def udp():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.setblocking(False)
    yield sock
    sock.close()


def datagrams(sock: socket.socket) -> int:
    n = 0
    while True:
        try:
            sock.recvfrom(4096)
        except BlockingIOError:
            return n
        n += 1


def url_of(server) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


async def templates(*, limit: int, max_chars: int = 60_000, need=lambda wf: True) -> list[tuple[str, dict]]:
    """Open-source templates this ComfyUI serves, in index order, that fit `max_chars` and pass `need`."""
    found = []
    async with httpx2.AsyncClient(base_url=URL, timeout=60) as http:
        index = (await http.get("/templates/index.json")).json()
        names = [t["name"] for c in index for t in c.get("templates", []) if t.get("openSource") is not False]
        for name in dict.fromkeys(names):
            wf = (await http.get(f"/templates/{name}.json")).json()
            if conv.is_ui_format(wf) and len(json.dumps(wf)) <= max_chars and need(wf):
                found.append((name, wf))
                if len(found) == limit:
                    break
    return found


async def comfyui_status(path: str) -> int:
    async with httpx2.AsyncClient(base_url=URL, timeout=10) as http:
        return (await http.get(path)).status_code


async def export(workflows: list[dict]) -> list[dict]:
    """The oracle: the frontend's own Export (API) in a plain browser, nothing blocked, a fresh context each. It
    loads through a stand-in, so the settings the frontend writes as it starts never reach ComfyUI."""
    from playwright.async_api import async_playwright

    out = []
    standin = _serve(StandIn(free_port()))
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            for wf in workflows:
                context = await browser.new_context()
                page = await context.new_page()
                await page.goto(url_of(standin), wait_until="load")
                await page.wait_for_function(conv._READY, polling=250, timeout=60_000)
                out.append(await page.evaluate(conv._CONVERT, wf))
                await context.close()
        finally:
            await browser.close()
            standin.shutdown()
            standin.server_close()
    return out


def escape_args(standin, canary, fresh, udp) -> list:
    return [url_of(standin), url_of(canary), CANARY_FILE, udp.getsockname()[1], url_of(fresh)]


async def test_the_negative_control_gets_out_so_the_lockdown_test_can_fail(standin, canary, fresh, udp):
    """A plain browser, the same script: everything gets out, so the lockdown test below can fail. If this stops
    being true (a Chromium change), that test would pass for the wrong reason. Nothing is written to ComfyUI: the
    stand-in answers every write itself."""
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url_of(standin), wait_until="load")
            await page.wait_for_function(conv._READY, polling=250, timeout=60_000)
            results = await page.evaluate(ESCAPES, escape_args(standin, canary, fresh, udp))
        finally:
            await browser.close()
    for name in (
        "post_comfyui",
        "put_comfyui",
        "delete_comfyui",
        "get_comfyui_off_allowlist",
        "get_other_origin",
        "nested_worker_post_comfyui",
        "shared_worker_from_blank_iframe",
        "shared_worker_from_srcdoc_iframe",
    ):
        assert results[name].startswith("reached"), (name, results[name])
    # The websockets reach the stand-in (ESCAPED_TO_COMFYUI), which doesn't upgrade them, so the page sees them fail.
    assert results["shared_worker"] == "reached: started" and results["beacon_other_origin"] == "reached: queued"
    got = set(standin.requests)
    assert ESCAPED_TO_COMFYUI <= got, ESCAPED_TO_COMFYUI - got
    assert {("POST", f"/api/userdata/{CANARY_FILE}"), ("PUT", f"/api/userdata/{CANARY_FILE}")} <= got
    seen = set(canary.requests)
    assert {"GET /fetch", "GET /worker", "POST /beacon", "GET /iframe", "GET /popup"} <= seen, seen
    assert any(r.startswith("GET /worker-ws") for r in seen), seen
    # Not asserted: the preconnect. Chromium's headless shell, as Playwright launches it, opened no connection for
    # one even here (measured with Playwright 1.63.0), so there is nothing to compare. The lockdown test still checks
    # that none is made.
    assert datagrams(udp) > 0  # WebRTC's STUN, and WebTransport's QUIC


async def test_the_lockdown_blocks_every_escape_and_conversion_still_works(standin, canary, fresh, udp):
    (name, workflow), *_ = await templates(limit=1, max_chars=30_000)
    converter = conv.Converter(url_of(standin), pages=1)
    try:
        before = await converter.convert(workflow)
        assert before and all("class_type" in n for n in before.values()), name
        tab = await converter._session.idle.get()  # the one tab, with the frontend loaded
        try:
            results = await tab.page.evaluate(ESCAPES, escape_args(standin, canary, fresh, udp))
        finally:
            converter._session.idle.put_nowait(tab)
        await asyncio.sleep(1)

        for k in ONLY_THE_SERVERS_KNOW:
            results.pop(k)
        assert all(r.startswith("blocked") for r in results.values()), json.dumps(results, indent=1)
        # Every request that reached "ComfyUI", from any channel, was an allowlisted GET the relay sent.
        unexpected = [(m, p) for m, p in standin.requests if not converter.allowed(m, url_of(standin) + p)]
        assert unexpected == [], unexpected
        assert canary.requests == [] and canary.connections == 0, (canary.requests, canary.connections)
        assert fresh.connections == 0
        assert datagrams(udp) == 0
        assert await comfyui_status(f"/api/userdata/{CANARY_FILE}") == 404

        blocked = set(converter.blocked)
        for method in ("POST", "PUT", "DELETE"):
            assert (method, f"{url_of(standin)}/api/userdata/{CANARY_FILE}") in blocked
        assert ("GET", f"{url_of(standin)}/api/prompt") in blocked  # ComfyUI's, GET, but not on the allowlist
        assert ("GET", f"{url_of(canary)}/fetch") in blocked
        assert ("GET", f"{url_of(canary)}/worker") in blocked
        assert ("POST", f"{url_of(canary)}/beacon") not in blocked  # sendBeacon is gone: nothing was sent
        assert any(m == "WS" for m, _ in blocked)

        assert await converter.convert(workflow) == before
    finally:
        await converter.close()


async def test_a_crashed_tab_is_unavailable_and_retryable_then_replaced():
    """R2 against a real browser: a renderer that crashes under a conversion is the browser's failure, not the
    graph's, so it is conversion_unavailable and retryable, and the next call gets a fresh tab."""
    (_, workflow), *_ = await templates(limit=1, max_chars=30_000)
    converter = conv.Converter(URL, pages=1)
    try:
        want = await converter.convert(workflow)
        tab = await converter._session.idle.get()
        cdp = await tab.page.context.new_cdp_session(tab.page)
        try:
            await asyncio.wait_for(cdp.send("Page.crash"), 5)
        except Exception:
            pass  # the target it was sent to is gone
        converter._session.idle.put_nowait(tab)
        with pytest.raises(RelayError) as caught:
            await converter.convert(workflow)
        assert caught.value.code == "conversion_unavailable" and caught.value.retryable, caught.value.message
        assert await converter.convert(workflow) == want
    finally:
        await converter.close()


# Asked for, refused on purpose, and not needed to convert: on a ComfyUI no browser has opened, the frontend's
# first-run template browser (it would go on to load every template's thumbnail).
NOT_NEEDED = {"/api/workflow_templates"}


async def test_the_allowlist_covers_everything_the_frontend_needs():
    """Every GET the frontend makes to ComfyUI while it loads and converts is on the allowlist: nothing it asked
    ComfyUI for was refused but NOT_NEEDED. (It does ask other hosts, and opens /ws; those are refused, and it
    converts anyway.)"""
    converter = conv.Converter(URL, pages=2)
    origin = conv._origin(URL)
    try:
        for _, wf in await templates(limit=12):
            await converter.convert(wf)
        refused = [
            (m, u)
            for m, u in converter.blocked
            if m == "GET" and conv._origin(u) == origin and urlsplit(u).path not in NOT_NEEDED
        ]
        assert refused == [], refused
    finally:
        await converter.close()


async def test_conversions_match_the_frontends_own_export():
    """D8's oracle method on a handful of templates, one of them with subgraphs: two tabs, recycled after every
    other conversion, so a recycled tab's first conversion is checked too."""
    picked = await templates(limit=5)
    picked += await templates(limit=1, need=lambda wf: bool((wf.get("definitions") or {}).get("subgraphs")))
    names = [n for n, _ in picked]
    assert len(set(names)) >= 5, names
    converter = conv.Converter(URL, pages=2)
    old = conv.RECYCLE_AFTER
    conv.RECYCLE_AFTER = 2
    try:
        got = [await converter.convert(wf) for _, wf in picked]
    finally:
        conv.RECYCLE_AFTER = old
        await converter.close()
    want = await export([wf for _, wf in picked])
    for name, g, w in zip(names, got, want, strict=True):
        assert g == w, name


async def test_load3d_cant_upload_while_converting_so_it_fails():
    """Load3D's serialization POSTs /api/upload/image during graphToPrompt; the lockdown refuses it, so such a graph
    fails to convert rather than writing to ComfyUI."""

    def load3d(wf: dict) -> bool:
        return '"Load3D' in json.dumps(wf)

    async with httpx2.AsyncClient(base_url=URL, timeout=60) as http:
        index = (await http.get("/templates/index.json")).json()
        candidates = []
        for name in dict.fromkeys(t["name"] for c in index for t in c.get("templates", [])):
            wf = (await http.get(f"/templates/{name}.json")).json()
            if conv.is_ui_format(wf) and load3d(wf):
                candidates.append((name, wf))
    assert candidates, "no template with a Load3D node is served"
    converter = conv.Converter(URL, pages=1)
    failures = []
    try:
        for name, wf in candidates:
            try:
                await converter.convert(wf)
            except RelayError as exc:
                failures.append((name, exc.code))
        uploads = [u for m, u in converter.blocked if m == "POST" and urlsplit(u).path == "/api/upload/image"]
    finally:
        await converter.close()
    assert uploads, "no Load3D template tried to upload"
    assert failures and all(code == "conversion_failed" for _, code in failures), failures


def _rss_mb(field: str) -> float:
    with open("/proc/self/status") as f:
        return next(int(line.split()[1]) for line in f if line.startswith(field)) / 1024


async def test_large_answers_are_refused_and_never_balloon_the_relay(standin):
    """What once OOM-killed the relay (#191): a LoadVideo graph whose input file is hundreds of MB, and many answers
    at once. The preview's video comes in ranges cut to RANGE_BYTES. An answer over the cap is given up on as it
    streams, chunked or not, and the page gets an abort; answers under it are fetched a few at a time. The relay
    runs in this process, so its own peak memory is measured here."""
    (_, workflow), *_ = await templates(limit=1, need=lambda wf: '"LoadVideo"' in json.dumps(wf))
    nodes = list(workflow["nodes"]) + [
        n for g in (workflow.get("definitions") or {}).get("subgraphs") or [] for n in g["nodes"]
    ]
    for node in nodes:
        if node.get("type") == "LoadVideo":
            node["widgets_values"][0] = "huge.mp4"
    converter = conv.Converter(url_of(standin), pages=1)
    try:
        await converter.convert(workflow)  # loads the frontend, and the graph with its 300 MB "input"
        with open("/proc/self/clear_refs", "w") as f:
            f.write("5")  # reset this process's peak RSS
        before = _rss_mb("VmRSS:")
        tab = await converter._session.idle.get()
        try:
            results = await tab.page.evaluate(
                """async (comfy) => {
                  const get = (p) => fetch(comfy + p).then(r => r.arrayBuffer())
                    .then(b => b.byteLength, e => 'aborted');
                  const big = [get('/assets/large-1.bin?mb=300'), get('/assets/large-2.bin?mb=300&chunked=1')];
                  const many = Array.from({length: 24}, (_, i) => get(`/assets/large-m${i}.bin?mb=20`));
                  return {big: await Promise.all(big), many: await Promise.all(many)};
                }""",
                url_of(standin),
            )
        finally:
            converter._session.idle.put_nowait(tab)
        peak = _rss_mb("VmHWM:")
    finally:
        await converter.close()
    assert results["big"] == ["aborted", "aborted"], results["big"]
    assert results["many"] == [20 * 1024 * 1024] * 24, results["many"]
    assert standin.views and max(standin.views) <= conv.RANGE_BYTES, standin.views  # the video, a range at a time
    for key in ("/assets/large-1.bin?mb=300", "/assets/large-2.bin?mb=300&chunked=1"):
        assert standin.sent.get(key, 0) < 200 * 1024 * 1024, (key, standin.sent.get(key))  # it stopped reading
    # Unbounded, the two large answers alone were 600 MB, and the 24 others 480 MB more.
    assert peak - before < 300, (before, peak)
