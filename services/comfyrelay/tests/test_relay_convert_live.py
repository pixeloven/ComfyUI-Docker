"""The converter (#167) against a real, booted ComfyUI and a real Chromium: its lockdown (D3), its allowlist, and
its conversions against the frontend's own export (the oracle, D8). Skipped unless COMFYRELAY_LIVE_COMFYUI_URL
names a ComfyUI and Playwright (the `convert` extra) and its Chromium are installed:

    cd services
    uv run --locked --extra convert playwright install --only-shell chromium
    COMFYRELAY_LIVE_COMFYUI_URL=http://127.0.0.1:8188 \\
      uv run --locked --extra convert pytest -q comfyrelay/tests/test_relay_convert_live.py

The lockdown test runs a page script that tries every way out it can, first in a plain browser (the negative
control: each one must get out, or the test proves nothing), then in a converter tab, where each must fail: POST,
PUT and DELETE to ComfyUI, a GET ComfyUI serves but the frontend doesn't need, GET to another origin (a canary
this test runs), api.comfy.org, websockets from the page and from a dedicated worker, a worker's fetch, a beacon,
a cross-origin iframe, a popup, a preconnect, WebRTC to a UDP socket this test holds, and WebTransport from a
worker. DNS prefetch isn't observable here: the resolver rule keeps it from sending any lookup by construction.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

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
CONTROL_FILE = "convert-lockdown-control.json"

ESCAPES = """async ([comfy, canary, file, udp, fresh]) => {
  const worker = (src) => new Promise((ok, no) => {
    const w = new Worker(URL.createObjectURL(new Blob([src], {type: 'text/javascript'})));
    w.onmessage = e => e.data.startsWith('ok') ? ok(e.data) : no(new Error(e.data));
    setTimeout(() => no(new Error('timeout')), 5000);
  });
  const ws = (u) => `try { const s = new WebSocket(${JSON.stringify(u)}); s.onopen = () => postMessage('ok open');
    s.onerror = () => postMessage('error'); } catch (e) { postMessage('threw ' + e); }`;
  const tries = {
    post_comfyui: () => fetch(comfy + '/api/userdata/' + file, {method: 'POST', body: '{"leaked": true}'}),
    put_comfyui: () => fetch(comfy + '/api/userdata/' + file, {method: 'PUT', body: '{}'}),
    delete_comfyui: () => fetch(comfy + '/api/userdata/' + file, {method: 'DELETE'}),
    get_comfyui_off_allowlist: () => fetch(comfy + '/api/prompt'),
    get_other_origin: () => fetch(canary + '/fetch'),
    get_api_comfy_org: () => fetch('https://api.comfy.org/'),
    websocket_comfyui: () => new Promise((ok, no) => {
      const s = new WebSocket(comfy.replace(/^http/, 'ws') + '/ws');
      s.onopen = () => ok('open');
      s.onerror = () => no(new Error('ws error'));
      s.onclose = () => no(new Error('ws closed'));
      setTimeout(() => no(new Error('ws timeout')), 5000);
    }),
    worker_fetch_other_origin: () => worker(`fetch(${JSON.stringify(canary + '/worker')})
      .then(() => postMessage('ok'), e => postMessage('blocked: ' + e))`),
    worker_websocket_comfyui: () => worker(ws(comfy.replace(/^http/, 'ws') + '/ws')),
    worker_websocket_other_origin: () => worker(ws(canary.replace(/^http/, 'ws') + '/worker-ws')),
    worker_webtransport: () => worker(`try { const t = new WebTransport('https://127.0.0.1:${udp}/');
      t.ready.then(() => postMessage('ok'), e => postMessage('failed ' + e)); }
      catch (e) { postMessage('threw ' + e); }`),
    shared_worker: async () => { new SharedWorker(URL.createObjectURL(new Blob([''], {type: 'text/javascript'})));
                                 return 'started'; },
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
  await new Promise(r => setTimeout(r, 1500));  // let beacons, iframes, popups and preconnects go, or not
  return out;
}"""
# Tries whose fate the page can't see (it only inserts or opens something); the canary can.
ONLY_THE_CANARY_KNOWS = {"iframe_other_origin", "popup_other_origin", "preconnect_other_origin"}


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


@pytest.fixture
def canary():
    server = Canary(free_port())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def fresh():
    """A second canary, for the preconnect alone: Chromium preconnects only to an origin it holds no idle
    connection to."""
    server = Canary(free_port())
    threading.Thread(target=server.serve_forever, daemon=True).start()
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
    """The oracle: the frontend's own Export (API) in a plain browser, nothing blocked, a fresh context each."""
    from playwright.async_api import async_playwright

    out = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            for wf in workflows:
                context = await browser.new_context()
                page = await context.new_page()
                await page.goto(URL, wait_until="load")
                await page.wait_for_function(conv._READY, polling=250, timeout=60_000)
                out.append(await page.evaluate(conv._CONVERT, wf))
                await context.close()
        finally:
            await browser.close()
    return out


async def escape_from_plain_browser(canary: Canary, fresh: Canary, sock: socket.socket) -> dict:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(URL, wait_until="load")
            await page.wait_for_function(conv._READY, polling=250, timeout=60_000)
            return await page.evaluate(
                ESCAPES, [URL, canary_url(canary), CONTROL_FILE, sock.getsockname()[1], canary_url(fresh)]
            )
        finally:
            await browser.close()


def canary_url(canary: Canary) -> str:
    return f"http://127.0.0.1:{canary.server_address[1]}"


async def test_the_lockdown_blocks_every_escape_and_conversion_still_works(canary, fresh, udp):
    (name, workflow), *_ = await templates(limit=1, max_chars=30_000)
    converter = conv.Converter(URL, pages=1)
    try:
        before = await converter.convert(workflow)
        assert before and all("class_type" in n for n in before.values()), name
        tab = await converter._session.idle.get()  # the one tab, with the frontend loaded
        try:
            results = await tab.page.evaluate(
                ESCAPES, [URL, canary_url(canary), CANARY_FILE, udp.getsockname()[1], canary_url(fresh)]
            )
        finally:
            converter._session.idle.put_nowait(tab)
        await asyncio.sleep(1)

        for k in ONLY_THE_CANARY_KNOWS:
            results.pop(k)
        assert all(r.startswith("blocked") for r in results.values()), json.dumps(results, indent=1)
        assert canary.requests == [] and canary.connections == 0, (canary.requests, canary.connections)
        assert fresh.connections == 0
        assert datagrams(udp) == 0
        assert await comfyui_status(f"/api/userdata/{CANARY_FILE}") == 404

        blocked = set(converter.blocked)
        for method in ("POST", "PUT", "DELETE"):
            assert (method, f"{URL}/api/userdata/{CANARY_FILE}") in blocked
        assert ("GET", f"{URL}/api/prompt") in blocked  # ComfyUI's, GET, but not on the allowlist
        assert ("GET", f"{canary_url(canary)}/fetch") in blocked
        assert ("GET", f"{canary_url(canary)}/worker") in blocked
        assert ("POST", f"{canary_url(canary)}/beacon") not in blocked  # sendBeacon is gone: nothing was sent
        assert any(m == "WS" for m, _ in blocked)

        assert await converter.convert(workflow) == before
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


async def test_the_negative_control_gets_out_so_the_lockdown_test_can_fail(canary, fresh, udp):
    """Without the lockdown, the same script reaches ComfyUI's write routes and the canaries. If this stops being
    true (a Chromium change, a sandbox), the lockdown test would pass for the wrong reason. Last in the file: a
    plain browser stores the frontend's settings in ComfyUI, and the converter tests above should meet a ComfyUI
    no browser has opened, as CI's is, where the frontend writes settings as it starts."""
    results = await escape_from_plain_browser(canary, fresh, udp)
    try:
        for name in ("post_comfyui", "get_comfyui_off_allowlist", "get_other_origin", "websocket_comfyui"):
            assert results[name].startswith("reached"), (name, results[name])
        assert results["worker_websocket_comfyui"] == "reached: ok open"
        # The POST wrote the file, and the DELETE removed it: ComfyUI answered both.
        assert results["post_comfyui"] == "reached: 200" and results["delete_comfyui"] in (
            "reached: 200",
            "reached: 204",
        )
        seen = set(canary.requests)
        assert {"GET /fetch", "GET /worker", "POST /beacon", "GET /iframe", "GET /popup"} <= seen, seen
        assert any(r.startswith("GET /worker-ws") for r in seen), seen
        # Not asserted: the preconnect. Chromium's headless shell, as Playwright launches it, opened no connection
        # for one even here (measured with Playwright 1.63.0), so there is nothing to compare. The lockdown test
        # still checks that none is made.
        assert results["shared_worker"] == "reached: started" and results["beacon_other_origin"] == "reached: queued"
        assert datagrams(udp) > 0  # WebRTC's STUN, and WebTransport's QUIC
    finally:
        async with httpx2.AsyncClient(base_url=URL, timeout=10) as http:
            await http.delete(f"/api/userdata/{CONTROL_FILE}")
