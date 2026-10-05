"""SPIKE (#167, D3): the converter's browser lockdown, against a real, booted ComfyUI and a real Chromium.
Skipped unless COMFYRELAY_LIVE_COMFYUI_URL names a ComfyUI and Playwright (the `convert` extra) and its
Chromium are installed:

    cd services
    uv run --locked --extra convert playwright install --only-shell chromium
    COMFYRELAY_LIVE_COMFYUI_URL=http://127.0.0.1:8188 \\
      uv run --locked --extra convert pytest -q comfyrelay/tests/test_relay_convert_live.py

A page script tries every way out it can: POST, PUT and DELETE to ComfyUI, a websocket to ComfyUI, GET to
another origin (a canary server this test runs) from the page, a worker and a beacon, and a fetch to
api.comfy.org. Each must fail in the page, reach neither the canary nor ComfyUI, and the conversion must still
work afterwards. Then WebRTC, which request interception does not see: a peer connection whose STUN server is a
UDP socket this test holds must send it nothing.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx2
import pytest
from comfyrelay.convert import Converter, is_ui_format
from relay_helpers import free_port

URL = os.environ.get("COMFYRELAY_LIVE_COMFYUI_URL", "").rstrip("/")
no_comfyui = pytest.mark.skipif(not URL, reason="COMFYRELAY_LIVE_COMFYUI_URL is not set")
no_browser = pytest.mark.skipif(
    importlib.util.find_spec("playwright") is None, reason="the convert extra is not installed"
)

CANARY_FILE = "spike167-lockdown-canary.json"

ESCAPES = """async ([comfy, canary, file]) => {
  const tries = {
    post_comfyui: () => fetch(comfy + '/api/userdata/' + file, {method: 'POST', body: '{"leaked": true}'}),
    put_comfyui: () => fetch(comfy + '/api/userdata/' + file, {method: 'PUT', body: '{}'}),
    delete_comfyui: () => fetch(comfy + '/api/userdata/' + file, {method: 'DELETE'}),
    get_other_origin: () => fetch(canary + '/fetch'),
    get_api_comfy_org: () => fetch('https://api.comfy.org/'),
    websocket_comfyui: () => new Promise((ok, no) => {
      const ws = new WebSocket(comfy.replace(/^http/, 'ws') + '/ws');
      ws.onopen = () => ok('open');
      ws.onerror = () => no(new Error('ws error'));
      ws.onclose = () => no(new Error('ws closed'));
      setTimeout(() => no(new Error('ws timeout')), 5000);
    }),
    worker_other_origin: () => new Promise((ok, no) => {
      const src = `fetch(${JSON.stringify(canary + '/worker')})` +
        `.then(() => postMessage('ok'), e => postMessage('blocked: ' + e))`;
      const w = new Worker(URL.createObjectURL(new Blob([src], {type: 'text/javascript'})));
      w.onmessage = e => e.data === 'ok' ? ok('ok') : no(new Error(e.data));
      setTimeout(() => no(new Error('worker timeout')), 5000);
    }),
    beacon_other_origin: async () => {
      if (!navigator.sendBeacon(canary + '/beacon', 'x')) throw new Error('beacon refused');
      await new Promise(r => setTimeout(r, 1000));
      return 'queued';
    },
  };
  const out = {};
  for (const [name, attempt] of Object.entries(tries)) {
    try { const r = await attempt(); out[name] = 'reached: ' + (r && r.status !== undefined ? r.status : r); }
    catch (e) { out[name] = 'blocked: ' + String(e).slice(0, 120); }
  }
  return out;
}"""


WEBRTC = """async (stun) => {
  const pc = new RTCPeerConnection({iceServers: [{urls: stun}]});
  pc.createDataChannel('x');
  const found = [];
  pc.onicecandidate = e => { if (e.candidate) found.push(e.candidate.candidate) };
  await pc.setLocalDescription(await pc.createOffer());
  await new Promise(r => setTimeout(r, 3000));
  pc.close();
  return found;
}"""


class Canary(BaseHTTPRequestHandler):
    seen: list[str] = []

    def _any(self) -> None:
        Canary.seen.append(f"{self.command} {self.path}")
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    do_GET = do_POST = do_PUT = do_DELETE = do_OPTIONS = _any

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def canary():
    port = free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), Canary)
    Canary.seen = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


async def _small_template() -> dict:
    async with httpx2.AsyncClient(base_url=URL, timeout=30) as http:
        index = (await http.get("/templates/index.json")).json()
        names = [t["name"] for c in index for t in c.get("templates", []) if t.get("openSource") is not False]
        for name in names:
            wf = (await http.get(f"/templates/{name}.json")).json()
            if is_ui_format(wf) and len(json.dumps(wf)) < 30_000:
                return wf
    pytest.skip("no small UI-format template served")


@pytest.mark.anyio
@no_comfyui
@no_browser
async def test_lockdown_blocks_every_escape_and_conversion_still_works(canary: str) -> None:
    workflow = await _small_template()
    converter = Converter(URL, pages=1)
    try:
        before = await converter.convert(workflow)
        assert before and all("class_type" in n for n in before.values())

        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.bind(("127.0.0.1", 0))
        udp.setblocking(False)
        page = await converter._idle.get()  # the spike's one tab, with the frontend loaded
        try:
            results = await page.evaluate(ESCAPES, [URL, canary, CANARY_FILE])
            candidates = await page.evaluate(WEBRTC, f"stun:127.0.0.1:{udp.getsockname()[1]}")
        finally:
            converter._idle.put_nowait(page)
        with udp:
            try:
                datagram = udp.recvfrom(2048)
            except BlockingIOError:
                datagram = None
        assert datagram is None and candidates == [], (datagram, candidates)

        # A page can't see a beacon's fate (sendBeacon only says it queued it): the canary and the log below can.
        assert results.pop("beacon_other_origin") == "reached: queued"
        assert all(r.startswith("blocked") for r in results.values()), json.dumps(results, indent=1)
        await asyncio.sleep(1)
        assert Canary.seen == [], Canary.seen
        async with httpx2.AsyncClient(base_url=URL, timeout=10) as http:
            assert (await http.get(f"/api/userdata/{CANARY_FILE}")).status_code == 404
        blocked = {(m, u) for m, u in converter.blocked}
        assert ("POST", f"{URL}/api/userdata/{CANARY_FILE}") in blocked
        assert ("PUT", f"{URL}/api/userdata/{CANARY_FILE}") in blocked
        assert ("DELETE", f"{URL}/api/userdata/{CANARY_FILE}") in blocked
        assert ("GET", f"{canary}/fetch") in blocked
        assert ("POST", f"{canary}/beacon") in blocked
        assert any(m == "WS" for m, _ in blocked)

        assert await converter.convert(workflow) == before
    finally:
        await converter.close()


def test_only_get_to_the_comfyui_origin_is_allowed() -> None:
    c = Converter("http://127.0.0.1:8188")
    assert c.allowed("GET", "http://127.0.0.1:8188/object_info")
    assert not c.allowed("POST", "http://127.0.0.1:8188/prompt")
    assert not c.allowed("GET", "http://127.0.0.1:8189/")
    assert not c.allowed("GET", "https://127.0.0.1:8188/")
    assert not c.allowed("GET", "https://api.comfy.org/releases")
    assert Converter("https://u:p@comfy.example/")._refused
