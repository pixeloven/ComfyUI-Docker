"""UI-to-API conversion (#167): the converter's lockdown rules and lifecycle with the browser faked, and the tools'
conversion surface (D4, D5) with the converter faked. The real browser, against a real ComfyUI, is
test_relay_convert_live.py."""

from __future__ import annotations

import asyncio
import json

import comfyrelay.convert as conv
import httpx2
import pytest
from comfyrelay.comfyui import ComfyUIClient
from comfyrelay.errors import RelayError
from comfyrelay.server import RelayServer, build_server
from comfyrelay.settings import ConfigError, Settings
from mcp import Client
from relay_helpers import SYSTEM_STATS, TOKEN, WORKFLOW_OBJECT_INFO, settings
from test_relay_introspection import routes as introspection_routes

pytestmark = pytest.mark.anyio

URL = "http://comfyui.test:8188"


# -- the lockdown's request rule ------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        f"{URL}/",
        f"{URL}/assets/index-abc.js",
        f"{URL}/fonts/inter.woff2",
        f"{URL}/extensions/core/groupNode.js",
        f"{URL}/api/object_info",
        f"{URL}/api/userdata?dir=workflows&recurse=true",
        f"{URL}/api/userdata/workflows%2Fx.json",
        f"{URL}/api/view?filename=example.png&type=input",
        f"{URL}/user.css",
    ],
)
def test_the_frontends_gets_to_comfyui_are_allowed(url):
    assert conv.Converter(URL).allowed("GET", url)


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("POST", f"{URL}/api/prompt"),
        ("POST", f"{URL}/api/upload/image"),
        ("PUT", f"{URL}/api/userdata/x.json"),
        ("DELETE", f"{URL}/api/userdata/x.json"),
        ("HEAD", f"{URL}/"),
        # Another origin: host, port or scheme.
        ("GET", "https://api.comfy.org/releases"),
        ("GET", "http://comfyui.test:8189/"),
        ("GET", "https://comfyui.test:8188/"),
        ("GET", "http://evil.test/"),
        # ComfyUI, but a route the frontend doesn't need: some GET routes act.
        ("GET", f"{URL}/api/prompt"),
        ("GET", f"{URL}/api/interrupt"),
        ("GET", f"{URL}/manager/reboot"),
        ("GET", f"{URL}/api/manager/queue/start"),
        ("GET", f"{URL}/object_info"),
        ("GET", f"{URL}/custom_route"),
        ("GET", f"{URL}/api/userdataX"),
        # Out of an allowed prefix once decoded.
        ("GET", f"{URL}/assets/../api/interrupt"),
        ("GET", f"{URL}/extensions/..%2Fmanager%2Freboot"),
        ("GET", f"{URL}/assets/%2e%2e/api/interrupt"),
        ("GET", f"{URL}/assets/%5C..%5Capi"),
    ],
)
def test_everything_else_is_refused(method, url):
    assert not conv.Converter(URL).allowed(method, url)


def test_settings_writes_are_answered_in_the_browser_and_nothing_else_is():
    c = conv.Converter(URL)
    assert c.settings_write("POST", f"{URL}/api/settings/Comfy.InstalledVersion")
    assert c.settings_write("POST", f"{URL}/api/settings")
    assert not c.allowed("POST", f"{URL}/api/settings/Comfy.InstalledVersion")  # still never sent
    for method, url in [
        ("POST", f"{URL}/api/upload/image"),
        ("POST", f"{URL}/api/userdata/x.json"),
        ("POST", f"{URL}/api/prompt"),
        ("DELETE", f"{URL}/api/settings/x"),
        ("POST", "http://evil.test/api/settings/x"),
        ("POST", f"{URL}/api/settings/../prompt"),
    ]:
        assert not c.settings_write(method, url), (method, url)


async def test_the_gate_answers_a_settings_write_and_aborts_the_rest():
    class Route:
        def __init__(self):
            self.did = None

        async def continue_(self):
            self.did = "continue"

        async def fulfill(self, **kw):
            self.did = ("fulfill", kw["status"])

        async def abort(self, why):
            self.did = "abort"

    class Request:
        def __init__(self, method, url):
            self.method, self.url = method, url

    c = conv.Converter(URL)
    for method, path, did in [
        ("GET", "/api/object_info", "continue"),
        ("POST", "/api/settings/Comfy.InstalledVersion", ("fulfill", 200)),
        ("POST", "/api/upload/image", "abort"),
        ("GET", "/api/prompt", "abort"),
    ]:
        route = Route()
        await c._gate(route, Request(method, f"{URL}{path}"))
        assert route.did == did, (method, path)
    assert [m for m, _ in c.blocked] == ["POST", "POST", "GET"]


def test_a_comfyui_behind_a_path_allows_only_under_it():
    c = conv.Converter("http://proxy.test/comfy/")
    assert c.allowed("GET", "http://proxy.test/comfy/")
    assert c.allowed("GET", "http://proxy.test/comfy/api/object_info")
    assert not c.allowed("GET", "http://proxy.test/api/object_info")
    assert not c.allowed("GET", "http://proxy.test/comfyx/api/object_info")


def test_the_launch_sends_everything_but_comfyuis_http_origin_to_a_dead_proxy():
    options = conv.Converter("http://comfyui:8188")._launch_options()
    assert options["proxy"] == {"server": conv.DEAD_PROXY, "bypass": "<-loopback>,http://comfyui:8188"}
    assert "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE comfyui" in options["args"]
    assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in options["args"]
    assert "--disable-quic" in options["args"]
    assert (
        conv.Converter("https://comfy.example")
        ._launch_options()["proxy"]["bypass"]
        .endswith("https://comfy.example:443")
    )


@pytest.mark.parametrize(
    ("url", "why"),
    [
        ("http://user:secret@comfyui.test:8188", "carries credentials"),
        ("http://:secret@comfyui.test:8188", "carries credentials"),
        ("ftp://comfyui.test", "no http(s) origin"),
    ],
)
async def test_a_comfyui_url_it_cant_lock_to_is_refused_without_a_browser(url, why, monkeypatch):
    c = conv.Converter(url)
    monkeypatch.setattr(c, "_browser", _never)
    with pytest.raises(RelayError) as caught:
        await c.convert(UI)
    assert caught.value.code == "conversion_unavailable" and why in caught.value.message
    assert "secret" not in caught.value.message
    assert c.status()["state"] == "unavailable"


async def test_without_playwright_it_says_which_image_converts(monkeypatch):
    monkeypatch.setattr(conv, "installed", lambda: False)
    c = conv.Converter(URL)
    with pytest.raises(RelayError) as caught:
        await c.convert(UI)
    assert "mcp-convert image" in caught.value.message
    assert "mcp-convert image" in conv.off_reason()


# -- the lifecycle, with the browser faked ---------------------------------------------

UI = {"nodes": [{"id": 1, "type": "SaveImage"}], "links": []}
API = {"1": {"class_type": "SaveImage", "inputs": {}}}


async def _never():
    raise AssertionError("the browser must not be launched")


class FakePage:
    def __init__(self, browser: FakeBrowser, context: FakeContext) -> None:
        self.browser = browser
        self.context = context
        self.converted = 0

    @property
    def closed(self) -> bool:
        return self.context.closed

    async def goto(self, url, **kw):
        if self.browser.load_fails:
            raise RuntimeError("net::ERR_CONNECTION_REFUSED")

    async def wait_for_function(self, *a, **kw):
        pass

    async def evaluate(self, script, workflow):
        self.converted += 1
        if self.browser.gate is not None:
            await self.browser.gate.wait()
        if workflow.get("throw"):
            raise RuntimeError("Error: DataCloneError")
        return API


class FakeContext:
    """A tab's own context: the lockdown is set on it, and closing it closes its page."""

    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser
        self.closed = False
        self.locked: list[str] = []

    async def add_init_script(self, script):
        self.locked.append("init")

    async def route(self, pattern, handler):
        self.locked.append("route")

    async def route_web_socket(self, pattern, handler):
        self.locked.append("websocket")

    async def new_page(self):
        page = FakePage(self.browser, self)
        self.browser.pages.append(page)
        return page

    async def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self) -> None:
        self.pages: list[FakePage] = []
        self.closed = False
        self.load_fails = False
        self.gate: asyncio.Event | None = None

    def is_connected(self) -> bool:
        return not self.closed

    async def close(self):
        self.closed = True

    async def new_context(self, **kw):
        assert kw["service_workers"] == "block"
        return FakeContext(self)


class FakePW:
    def __init__(self) -> None:
        self.stopped = False

    async def stop(self):
        self.stopped = True


class Launches:
    """Stands in for Converter._browser: each call is one launch, or a failure while `fail` is set."""

    def __init__(self) -> None:
        self.browsers: list[FakeBrowser] = []
        self.pws: list[FakePW] = []
        self.fail = False
        self.attempts = 0

    async def __call__(self):
        self.attempts += 1
        if self.fail:
            raise RuntimeError("Executable doesn't exist at /opt/playwright/chromium_headless_shell")
        browser, pw = FakeBrowser(), FakePW()
        self.browsers.append(browser)
        self.pws.append(pw)
        return pw, browser


def converter(monkeypatch, pages: int = 1) -> tuple[conv.Converter, Launches]:
    monkeypatch.setattr(conv, "installed", lambda: True)  # the browser is faked; Playwright needn't be there
    c = conv.Converter(URL, pages=pages)
    launches = Launches()
    monkeypatch.setattr(c, "_browser", launches)
    return c, launches


async def settle():
    for _ in range(20):
        await asyncio.sleep(0)


async def test_one_browser_serves_every_conversion(monkeypatch):
    c, launches = converter(monkeypatch, pages=2)
    assert c.status()["state"] == "ready"
    assert [await c.convert(UI) for _ in range(5)] == [API] * 5
    assert launches.attempts == 1 and len(launches.browsers[0].pages) == 2
    # Each tab is a context of its own, locked down before its page loads.
    contexts = {p.context for p in launches.browsers[0].pages}
    assert len(contexts) == 2 and all(c.locked == ["init", "route", "websocket"] for c in contexts)
    assert c.status() == {"state": "running", "pages": 2, "conversions": 5}


async def test_tabs_are_recycled_staggered(monkeypatch):
    monkeypatch.setattr(conv, "RECYCLE_AFTER", 4)
    c, launches = converter(monkeypatch, pages=2)
    await c.convert(UI)
    await settle()
    session = c._session
    # The first tabs are given 4 and 2 conversions, so they don't reload together.
    assert sorted(t.limit for t in session.idle._queue) == [2, 4]
    for _ in range(11):
        await c.convert(UI)
        await settle()
    pages = launches.browsers[0].pages
    closed = [p.converted for p in pages if p.closed]
    assert closed and all(n in (2, 4) for n in closed)
    assert sorted(t.limit for t in session.idle._queue) == [4, 4]  # every replacement gets the full budget
    assert sum(1 for p in pages if not p.closed) == 2


async def test_a_failed_conversion_says_why_and_replaces_its_tab(monkeypatch):
    c, launches = converter(monkeypatch)
    with pytest.raises(RelayError) as caught:
        await c.convert({**UI, "throw": True})
    assert caught.value.code == "conversion_failed" and "DataCloneError" in caught.value.message
    assert not caught.value.retryable
    await settle()
    first, second = launches.browsers[0].pages
    assert first.closed and not second.closed
    assert await c.convert(UI) == API


async def test_a_slow_conversion_times_out_as_failed(monkeypatch):
    monkeypatch.setattr(conv, "CONVERT_SECONDS", 0.05)
    c, launches = converter(monkeypatch)
    await c.convert(UI)
    launches.browsers[0].gate = asyncio.Event()
    with pytest.raises(RelayError) as caught:
        await c.convert(UI)
    assert caught.value.code == "conversion_failed" and "no answer" in caught.value.message


async def test_a_launch_that_fails_backs_off_instead_of_retrying_every_call(monkeypatch):
    monkeypatch.setattr(conv, "LAUNCH_BACKOFF_SECONDS", 0.2)
    c, launches = converter(monkeypatch)
    launches.fail = True
    with pytest.raises(RelayError) as first:
        await c.convert(UI)
    assert first.value.code == "conversion_unavailable" and first.value.retryable
    assert "Executable doesn't exist" in first.value.message
    with pytest.raises(RelayError) as second:
        await c.convert(UI)
    assert "next attempt is in" in second.value.message
    assert launches.attempts == 1  # the second call didn't launch
    assert c.status()["state"] == "backing_off" and c.status()["retry_in_seconds"] <= 0.2
    await asyncio.sleep(0.25)
    with pytest.raises(RelayError):
        await c.convert(UI)
    assert launches.attempts == 2
    assert c._retry_at - asyncio.get_running_loop().time() > 0.3  # doubled
    launches.fail = False
    c._retry_at = 0
    assert await c.convert(UI) == API
    assert c._failures == 0


async def test_a_frontend_that_wont_load_is_unavailable_and_retried_next_call_without_a_relaunch(monkeypatch):
    c, launches = converter(monkeypatch)
    real = launches.__call__

    async def failing_loads():
        pw, browser = await real()
        browser.load_fails = True
        return pw, browser

    monkeypatch.setattr(c, "_browser", failing_loads)
    with pytest.raises(RelayError) as caught:
        await c.convert(UI)
    assert caught.value.code == "conversion_unavailable" and caught.value.retryable
    assert "ERR_CONNECTION_REFUSED" in caught.value.message
    launches.browsers[0].load_fails = False
    assert await c.convert(UI) == API
    assert launches.attempts == 1


async def test_the_browser_restarts_after_its_budget_once_its_conversions_finish(monkeypatch):
    monkeypatch.setattr(conv, "RESTART_AFTER", 3)
    c, launches = converter(monkeypatch, pages=2)
    for _ in range(2):
        await c.convert(UI)
    first = launches.browsers[0]
    first.gate = asyncio.Event()
    running = asyncio.ensure_future(c.convert(UI))  # the third: it reaches the budget
    await settle()
    later = asyncio.ensure_future(c.convert(UI))  # waits for the old browser to drain, then gets a new one
    await settle()
    assert not first.closed and len(launches.browsers) == 1
    first.gate.set()
    assert await running == API
    assert await later == API
    assert first.closed and launches.pws[0].stopped
    assert len(launches.browsers) == 2 and not launches.browsers[1].closed


async def test_a_browser_that_went_away_is_replaced(monkeypatch):
    c, launches = converter(monkeypatch)
    await c.convert(UI)
    launches.browsers[0].closed = True
    assert await c.convert(UI) == API
    assert len(launches.browsers) == 2


async def test_close_stops_the_browser_and_refuses_what_comes_after(monkeypatch):
    c, launches = converter(monkeypatch)
    await c.convert(UI)
    await c.close()
    assert launches.browsers[0].closed and launches.pws[0].stopped
    with pytest.raises(RelayError) as caught:
        await c.convert(UI)
    assert "stopping" in caught.value.message
    assert c.status()["state"] == "stopped"


async def test_the_server_closes_the_converter_as_it_shuts_down(monkeypatch):
    """After uvicorn's own shutdown and the jobs'. A real SIGTERM with a browser running is tests/relay/run.sh's."""
    import uvicorn

    closed = asyncio.Event()

    class Recorder:
        async def close(self):
            closed.set()

    async def uvicorns_own(self, sockets=None):
        pass

    monkeypatch.setattr(uvicorn.Server, "shutdown", uvicorns_own)
    s = settings()
    server = RelayServer(uvicorn.Config(lambda *a: None), build_server(s)[1].jobs, Recorder())
    await server.shutdown()
    assert closed.is_set()


# -- settings ----------------------------------------------------------------------------


def _load(**env) -> Settings:
    return Settings.load(
        comfyui_url=URL, host="127.0.0.1", port=9000, profiles="read,run", env={"COMFYUI_MCP_HTTP_TOKEN": TOKEN, **env}
    )


def test_conversion_is_off_unless_set_to_1():
    assert _load().convert is False
    assert _load(COMFYUI_MCP_CONVERT="0").convert is False
    assert (s := _load(COMFYUI_MCP_CONVERT="1")).convert is True and s.convert_pages == 2
    assert _load(COMFYUI_MCP_CONVERT_PAGES="8").convert_pages == 8
    with pytest.raises(ConfigError, match="over 8"):
        _load(COMFYUI_MCP_CONVERT_PAGES="9")
    with pytest.raises(ConfigError):
        _load(COMFYUI_MCP_CONVERT_PAGES="0")


# -- the tools (D4, D5), with the converter faked ---------------------------------------


class FakeConverter:
    """Converts any UI graph to `result`, or raises `error`; records what it was given."""

    def __init__(self, result=None, error: RelayError | None = None) -> None:
        self.result = result if result is not None else API
        self.error = error
        self.given: list[dict] = []

    async def convert(self, workflow):
        self.given.append(workflow)
        if self.error:
            raise self.error
        return self.result

    def status(self):
        return {"state": "running", "pages": 2, "conversions": len(self.given)}


SUB = "9d1c2e1a-0000-4000-8000-0000000000aa"
UI_SAVE = {
    "nodes": [{"id": 4, "type": "LoadImage", "mode": 0}, {"id": 9, "type": "SaveImage", "mode": 0}],
    "links": [[1, 4, 0, 9, 0, "IMAGE"]],
}
UI_PARTNER = {
    "nodes": [
        {"id": 3, "type": "ClaudeNode", "mode": 4},  # bypassed: it doesn't run
        {"id": 5, "type": SUB, "mode": 0},
        {"id": 9, "type": "PreviewAny", "mode": 0},
    ],
    "links": [],
    "definitions": {"subgraphs": [{"id": SUB, "nodes": [{"id": 2, "type": "ClaudeNode", "mode": 0}]}]},
}
CONVERTED = {
    "4": {"class_type": "LoadImage", "inputs": {"image": "in.png"}},
    "9": {"class_type": "SaveImage", "inputs": {"images": ["4", 0], "filename_prefix": "x"}},
}


def workflow_comfyui(posted: list) -> ComfyUIClient:
    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path == "/object_info":
            return httpx2.Response(200, json=WORKFLOW_OBJECT_INFO)
        if path == "/system_stats":
            return httpx2.Response(200, json=SYSTEM_STATS)
        if path == "/prompt" and request.method == "POST":
            body = json.loads(request.content)
            posted.append(body)
            return httpx2.Response(200, json={"prompt_id": body["prompt_id"], "number": 1, "node_errors": {}})
        if path.startswith("/api/jobs/"):
            return httpx2.Response(200, json={"id": path.rsplit("/", 1)[1], "status": "pending"})
        if path == "/queue":
            return httpx2.Response(200, json={"queue_running": [], "queue_pending": []})
        return httpx2.Response(404)

    return ComfyUIClient(URL, transport=httpx2.MockTransport(handler))


async def run_tool(tool, args, *, converter=None, comfyui=None, profiles=("read", "run")):
    server, relay = build_server(settings(profiles=profiles), comfyui=comfyui or workflow_comfyui([]))
    relay.converter = converter
    async with Client(server, mode="legacy") as mcp:
        result = await mcp.call_tool(tool, args)
    if result.is_error:
        text = result.content[0].text
        return json.loads(text[text.index("{") :])["error"]
    return result.structured_content


def template_comfyui() -> ComfyUIClient:
    table = introspection_routes()

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.raw_path.decode()
        if path in table:
            return table[path]
        return httpx2.Response(200, json={}) if path.startswith("/object_info/") else httpx2.Response(404)

    return ComfyUIClient(URL, transport=httpx2.MockTransport(handler))


async def test_template_get_api_returns_what_the_frontend_converts():
    fake = FakeConverter()
    got = await run_tool(
        "template_get", {"name": "sd15_simple", "format": "api"}, converter=fake, comfyui=template_comfyui()
    )
    assert (got["workflow"], got["format"], got["converted_from_ui"]) == (API, "api", True)
    assert fake.given[0]["nodes"][0]["type"] == "CheckpointLoaderSimple"  # it was handed the UI graph
    assert got["runnability"]["runnable"] is True  # still checked on the UI graph's nodes and models
    ui = await run_tool("template_get", {"name": "sd15_simple"}, converter=fake, comfyui=template_comfyui())
    assert (ui["format"], ui["converted_from_ui"]) == ("ui", False) and "nodes" in ui["workflow"]
    lean = await run_tool(
        "template_get",
        {"name": "sd15_simple", "format": "api", "include_workflow": False},
        converter=fake,
        comfyui=template_comfyui(),
    )
    assert "workflow" not in lean and len(fake.given) == 1  # nothing to convert


async def test_template_get_api_without_conversion_is_unavailable_with_the_ui_graph():
    err = await run_tool("template_get", {"name": "sd15_simple", "format": "api"}, comfyui=template_comfyui())
    assert err["code"] == "conversion_unavailable" and err["retryable"] is False
    assert "no fallback converter" in err["message"]
    assert err["workflow_format"] == "ui" and err["workflow"]["nodes"][0]["type"] == "CheckpointLoaderSimple"


async def test_template_get_api_failure_says_why_and_leaves_out_a_ui_graph_too_large(monkeypatch):
    from comfyrelay import tools_introspection

    fake = FakeConverter(error=conv.failed("Error: DataCloneError"))
    err = await run_tool(
        "template_get", {"name": "sd15_simple", "format": "api"}, converter=fake, comfyui=template_comfyui()
    )
    assert err["code"] == "conversion_failed" and "DataCloneError" in err["message"]
    assert "nodes" in err["workflow"]
    monkeypatch.setattr(tools_introspection, "WORKFLOW_MAX_CHARS", 50)
    err = await run_tool(
        "template_get", {"name": "sd15_simple", "format": "api"}, converter=fake, comfyui=template_comfyui()
    )
    assert "workflow" not in err and "over 50" in err["workflow_omitted"]


async def test_template_get_api_caps_the_converted_graph(monkeypatch):
    from comfyrelay import tools_introspection

    monkeypatch.setattr(tools_introspection, "WORKFLOW_MAX_CHARS", 30)
    big = {str(i): {"class_type": "SaveImage", "inputs": {}} for i in range(5)}
    err = await run_tool(
        "template_get",
        {"name": "sd15_simple", "format": "api"},
        converter=FakeConverter(big),
        comfyui=template_comfyui(),
    )
    assert err["code"] == "workflow_too_large" and "once converted" in err["message"]


async def test_validate_converts_a_ui_graph_and_returns_what_it_checked():
    fake = FakeConverter(CONVERTED)
    got = await run_tool("workflow_validate", {"workflow": UI_SAVE}, converter=fake)
    assert got["converted_from_ui"] is True and got["valid"] is True
    assert got["workflow"] == CONVERTED and got["output_nodes"] == ["9"]
    # An API graph is never sent to the converter.
    api = await run_tool("workflow_validate", {"workflow": CONVERTED}, converter=fake)
    assert api["converted_from_ui"] is False and api["workflow"] is None and len(fake.given) == 1


async def test_validate_leaves_out_a_converted_graph_too_large(monkeypatch):
    import comfyrelay.tools_workflow as tw

    monkeypatch.setattr(tw, "WORKFLOW_MAX_CHARS", 40)
    got = await run_tool("workflow_validate", {"workflow": UI_SAVE}, converter=FakeConverter(CONVERTED))
    assert got["converted_from_ui"] is True and got["workflow"] is None
    assert "over 40" in got["workflow_omitted"]


async def test_without_conversion_a_ui_graph_is_refused_as_before():
    got = await run_tool("workflow_validate", {"workflow": UI_SAVE})
    assert got["valid"] is False and got["errors"][0]["type"] == "invalid_workflow"
    assert got["converted_from_ui"] is False


@pytest.mark.parametrize("tool", ["workflow_validate", "workflow_run"])
async def test_a_conversion_failure_is_the_tools_error_and_nothing_is_submitted(tool):
    posted: list = []
    fake = FakeConverter(error=conv.unavailable("the browser did not start (x)", retryable=True))
    err = await run_tool(tool, {"workflow": UI_SAVE}, converter=fake, comfyui=workflow_comfyui(posted))
    assert err["code"] == "conversion_unavailable" and err["retryable"] is True
    assert posted == []


async def test_run_converts_a_ui_graph_and_submits_the_converted_one():
    posted: list = []
    got = await run_tool(
        "workflow_run", {"workflow": UI_SAVE}, converter=FakeConverter(CONVERTED), comfyui=workflow_comfyui(posted)
    )
    assert got["converted_from_ui"] is True
    assert posted[0]["prompt"] == CONVERTED
    assert "extra_data" not in posted[0]


async def test_run_refuses_partner_nodes_on_the_ui_graph_before_converting():
    posted: list = []
    fake = FakeConverter(error=conv.failed("POST /api/upload/image was blocked"))
    err = await run_tool("workflow_run", {"workflow": UI_PARTNER}, converter=fake, comfyui=workflow_comfyui(posted))
    assert err["code"] == "partner_api_nodes_refused"
    # The one inside the subgraph, named as the API graph would name it; not the bypassed one.
    assert [(n["node_id"], n["class_type"]) for n in err["nodes"]] == [("5:2", "ClaudeNode")]
    assert fake.given == [] and posted == []


async def test_server_info_says_whether_this_server_converts():
    off = await run_tool("server_info", {})
    assert off["capabilities"]["conversion"]["state"] == "off"
    assert off["capabilities"]["conversion"]["reason"]
    on = await run_tool("server_info", {}, converter=FakeConverter())
    assert on["capabilities"]["conversion"] == {"state": "running", "pages": 2, "conversions": 0}


async def test_the_tool_schemas_offer_conversion_honestly_either_way():
    server, _ = build_server(settings())
    async with Client(server, mode="legacy") as mcp:
        tools = {t.name: t for t in (await mcp.list_tools()).tools}
    fmt = tools["template_get"].input_schema["properties"]["format"]
    assert fmt["enum"] == ["ui", "api"] and fmt["default"] == "ui"
    assert "conversion_unavailable" in fmt["description"]
    assert (
        "server_info.capabilities.conversion"
        in tools["workflow_run"].input_schema["properties"]["workflow"]["description"]
    )
