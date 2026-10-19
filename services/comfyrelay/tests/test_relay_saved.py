"""The saved-workflow tools (#216) against a fake ComfyUI that serves /api/userdata the way v0.38.0 does
(app/user_manager.py): names, caps, the overwrite refusal, error mapping, and the byte-faithful round trip. The
real-ComfyUI counterpart is test_relay_saved_live.py."""

from __future__ import annotations

import json
import posixpath
from urllib.parse import unquote

import comfyrelay.tools_saved as ts
import httpx2
import pytest
from comfyrelay.errors import RelayError
from comfyrelay.server import build_server
from mcp import Client
from relay_helpers import settings
from test_relay_workflow_tools import FakeComfyUI, error_of, t1

pytestmark = pytest.mark.anyio

UI = {
    "id": "6f0c2b1e-0000-4000-8000-000000000000",
    "revision": 0,
    "last_node_id": 2,
    "last_link_id": 1,
    "nodes": [
        {"id": 1, "type": "EmptyImage", "widgets_values": [64, 64, 1, 0], "outputs": [{"links": [1]}]},
        {"id": 2, "type": "SaveImage", "widgets_values": ["portrait"], "inputs": [{"link": 1}]},
    ],
    "links": [[1, 1, 0, 2, 0, "IMAGE"]],
    "groups": [],
    "config": {},
    "extra": {"ds": {"scale": 0.75, "offset": [12.5, -3]}, "note": "café ✓"},
    "version": 0.4,
}


def js_stringify(value) -> bytes:
    """JSON.stringify(value) for the values these tests use: compact, non-ASCII as is."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


class UserdataComfyUI(FakeComfyUI):
    """FakeComfyUI plus the default user's files, served as ComfyUI's userdata routes serve them."""

    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        super().__init__()
        self.userdata: dict[str, bytes] = dict(files or {})
        self.modified: dict[str, int] = {}
        self.tick = 1_790_000_000_000
        self.userdata_calls: list[tuple[str, str]] = []
        self.userdata_status: int | None = None  # every userdata route answers this, when set
        for path in self.userdata:
            self._touch(path)

    def _touch(self, path: str) -> None:
        self.tick += 1000
        self.modified[path] = self.tick

    @staticmethod
    def _resolve(raw: str) -> str | None:
        """As aiohttp then get_request_user_filepath resolve it: one decode by the router, another if a % is left,
        and nothing outside the user's directory."""
        name = unquote(raw)
        if "%" in name:
            name = unquote(name)
        resolved = posixpath.normpath(posixpath.join("/user/default", name))
        return resolved[len("/user/default/") :] if resolved.startswith("/user/default/") else None

    async def handle(self, request: httpx2.Request) -> httpx2.Response:
        raw = request.url.raw_path.decode().split("?")[0]
        if not raw.startswith("/api/userdata"):
            return await super().handle(request)
        self.userdata_calls.append((request.method, raw))
        if self.userdata_status is not None:
            return httpx2.Response(self.userdata_status)
        if raw == "/api/userdata":
            folder = request.url.params["dir"]
            files = {p: b for p, b in self.userdata.items() if p.startswith(f"{folder}/")}
            if not files:
                return httpx2.Response(404, text="Directory not found")
            return httpx2.Response(
                200,
                json=[
                    {"path": p[len(folder) + 1 :], "size": len(b), "modified": self.modified[p]}
                    for p, b in files.items()
                ],
            )
        path = self._resolve(raw[len("/api/userdata/") :])
        if path is None:
            return httpx2.Response(403)
        if request.method == "GET":
            if path not in self.userdata:
                return httpx2.Response(404)
            return httpx2.Response(200, content=self.userdata[path])
        if request.method == "POST":
            if request.url.params.get("overwrite") == "false" and path in self.userdata:
                return httpx2.Response(409, text="File already exists")
            self.userdata[path] = request.content
            self._touch(path)
            return httpx2.Response(200, json={"path": path, "size": len(request.content), "modified": self.tick})
        return httpx2.Response(405)


async def call(fake: UserdataComfyUI, tool: str, args: dict, **overrides):
    server, _ = build_server(settings(**overrides), comfyui=fake.client())
    async with Client(server, mode="legacy") as client:
        return await client.call_tool(tool, args)


# -- names --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "../secrets.json",
        "a/../../comfy.settings.json",
        "workflows/../comfy.settings.json",
        "/etc/passwd.json",
        "..\\..\\x.json",
        "a\\b.json",
        "..%2Fcomfy.settings.json",
        "%2e%2e/x.json",
        "x.json\x00.png",
        "x\n.json",
        "a//b.json",
        "./x.json",
        "sub/./x.json",
        ".hidden.json",
        "sub/.git/x.json",
        "x.txt",
        "portrait",
        "",
        "workflows/",
        "a" * 300 + ".json",
        "é" * 200 + ".json",
    ],
)
async def test_a_bad_name_is_refused_before_anything_reaches_comfyui(name):
    fake = UserdataComfyUI({"comfy.settings.json": b"{}", "workflows/x.json": js_stringify(UI)})
    for tool, args in (
        ("workflow_get_saved", {"name": name}),
        ("workflow_save", {"name": name, "workflow": UI, "overwrite": True}),
        ("workflow_run", {"saved": name}),
        ("workflow_validate", {"saved": name}),
    ):
        error = error_of(await call(fake, tool, args))
        assert error["code"] == "invalid_workflow_name", (tool, error)
    assert fake.userdata_calls == []
    assert fake.userdata["comfy.settings.json"] == b"{}"


@pytest.mark.parametrize(
    ("name", "checked"),
    [
        ("t9-portrait.json", "t9-portrait.json"),
        ("workflows/t9-portrait.json", "t9-portrait.json"),
        ("portraits/old one (2).json", "portraits/old one (2).json"),
        ("ünïcödé ✓.json", "ünïcödé ✓.json"),
        ("a..b.json", "a..b.json"),
    ],
)
def test_good_names_are_relative_to_the_workflows_folder(name, checked):
    assert ts.saved_name(name) == checked


def test_a_name_without_json_says_what_it_would_be():
    with pytest.raises(RelayError) as caught:
        ts.saved_name("portrait")
    assert caught.value.detail["expected"] == "portrait.json"


async def test_the_name_is_sent_as_one_encoded_segment():
    fake = UserdataComfyUI({"workflows/sub dir/x.json": js_stringify(UI)})
    got = await call(fake, "workflow_get_saved", {"name": "sub dir/x.json"})
    assert not got.is_error, got.content[0].text
    assert fake.userdata_calls == [("GET", "/api/userdata/workflows%2Fsub%20dir%2Fx.json")]


# -- workflow_list_saved -----------------------------------------------------------------


async def test_the_list_is_newest_first_and_only_workflows():
    fake = UserdataComfyUI(
        {
            "workflows/old.json": b"{}",
            "workflows/sub/new.json": b"{}",
            "workflows/notes.txt": b"",
            "workflows/.hidden.json": b"{}",
            "comfy.settings.json": b"{}",
        }
    )
    got = (await call(fake, "workflow_list_saved", {}, profiles=("read",))).structured_content
    assert [w["name"] for w in got["workflows"]] == ["sub/new.json", "old.json"]
    assert got["total"] == 2 and got["omitted"] == 0 and got["unaddressable"] == 1
    assert got["folder"] == "user/default/workflows"
    assert got["workflows"][0]["size_bytes"] == 2
    assert got["workflows"][0]["modified"] == fake.modified["workflows/sub/new.json"] / 1000


async def test_the_list_is_capped(monkeypatch):
    monkeypatch.setattr(ts, "MAX_LISTED", 3)
    fake = UserdataComfyUI({f"workflows/w{i}.json": b"{}" for i in range(10)})
    got = (await call(fake, "workflow_list_saved", {})).structured_content
    assert [w["name"] for w in got["workflows"]] == ["w9.json", "w8.json", "w7.json"]
    assert got["total"] == 10 and got["omitted"] == 7


async def test_no_workflows_folder_is_an_empty_list():
    got = (await call(UserdataComfyUI(), "workflow_list_saved", {})).structured_content
    assert got["total"] == 0 and got["workflows"] == []


# -- workflow_get_saved ----------------------------------------------------------------


async def test_get_returns_the_workflow_and_its_format():
    api = t1()
    fake = UserdataComfyUI({"workflows/ui.json": js_stringify(UI), "workflows/api.json": js_stringify(api)})
    ui = (await call(fake, "workflow_get_saved", {"name": "ui.json"}, profiles=("read",))).structured_content
    assert ui == {"name": "ui.json", "format": "ui", "size_bytes": len(js_stringify(UI)), "workflow": UI}
    got = (await call(fake, "workflow_get_saved", {"name": "workflows/api.json"})).structured_content
    assert got["format"] == "api" and got["workflow"] == api and got["name"] == "api.json"


async def test_an_unknown_name_suggests_close_ones():
    fake = UserdataComfyUI({"workflows/t9-portrait.json": b"{}", "workflows/landscape.json": b"{}"})
    error = error_of(await call(fake, "workflow_get_saved", {"name": "t9_portrait.json"}))
    assert error["code"] == "unknown_saved_workflow"
    assert error["suggestions"] == ["t9-portrait.json"]


async def test_the_suggestions_are_optional():
    """Listing them fails, and the error is the same without them."""
    fake = UserdataComfyUI({"workflows/t9-portrait.json": b"{}"})
    real = fake.handle

    async def handle(request):
        if request.url.raw_path.decode().startswith("/api/userdata?"):
            raise httpx2.ConnectError("refused", request=request)
        return await real(request)

    fake.handle = handle
    error = error_of(await call(fake, "workflow_get_saved", {"name": "t9_portrait.json"}))
    assert error["code"] == "unknown_saved_workflow" and error["suggestions"] == []


async def test_reads_are_capped(monkeypatch):
    monkeypatch.setattr(ts, "MAX_SAVED_BYTES", 100)
    fake = UserdataComfyUI({"workflows/big.json": js_stringify(UI)})
    for tool in ("workflow_get_saved", "workflow_run"):
        error = error_of(await call(fake, tool, {"name" if tool == "workflow_get_saved" else "saved": "big.json"}))
        assert error["code"] == "saved_workflow_too_large" and error["limit"] == 100


async def test_a_workflow_too_large_to_return_says_run_takes_it_by_name(monkeypatch):
    monkeypatch.setattr(ts, "WORKFLOW_MAX_CHARS", 100)
    fake = UserdataComfyUI({"workflows/big.json": js_stringify(UI)})
    error = error_of(await call(fake, "workflow_get_saved", {"name": "big.json"}))
    assert error["code"] == "workflow_too_large" and "saved" in error["message"]


@pytest.mark.parametrize("content", [b"not json", b"[1, 2]", b"\xff\xfe", b""])
async def test_a_file_that_isnt_a_workflow(content):
    fake = UserdataComfyUI({"workflows/bad.json": content})
    error = error_of(await call(fake, "workflow_get_saved", {"name": "bad.json"}))
    assert error["code"] == "invalid_saved_workflow"


# -- workflow_save -------------------------------------------------------------------------


async def test_save_writes_a_new_file_as_the_editor_would():
    fake = UserdataComfyUI()
    got = await call(fake, "workflow_save", {"name": "new.json", "workflow": UI})
    assert got.structured_content == {
        "name": "new.json",
        "written": True,
        "replaced": False,
        "size_bytes": len(js_stringify(UI)),
    }
    assert fake.userdata["workflows/new.json"] == js_stringify(UI)
    assert fake.userdata_calls == [("POST", "/api/userdata/workflows%2Fnew.json")]


async def test_saving_onto_an_existing_name_needs_overwrite():
    held = json.dumps(UI, indent=2).encode()
    fake = UserdataComfyUI({"workflows/t9.json": held})
    edited = {**UI, "nodes": [UI["nodes"][0], {**UI["nodes"][1], "widgets_values": ["t9_"]}]}
    error = error_of(await call(fake, "workflow_save", {"name": "t9.json", "workflow": edited}))
    assert error["code"] == "workflow_exists"
    assert "overwrite: true" in error["message"] and error["path"] == "workflows/t9.json"
    assert fake.userdata["workflows/t9.json"] == held

    got = (
        await call(fake, "workflow_save", {"name": "t9.json", "workflow": edited, "overwrite": True})
    ).structured_content
    assert got["written"] is True and got["replaced"] is True
    assert fake.userdata["workflows/t9.json"] == js_stringify(edited)


async def test_a_round_trip_without_edits_leaves_the_bytes_alone():
    """Read and saved back unchanged: an editor-written file is the same bytes either way, and one another tool
    formatted isn't rewritten at all."""
    for held in (js_stringify(UI), json.dumps(UI, indent=2).encode()):
        fake = UserdataComfyUI({"workflows/t9.json": held})
        read = (await call(fake, "workflow_get_saved", {"name": "t9.json"})).structured_content["workflow"]
        got = await call(fake, "workflow_save", {"name": "t9.json", "workflow": read, "overwrite": True})
        assert got.structured_content["written"] is False
        assert fake.userdata["workflows/t9.json"] == held
        assert ("POST", "/api/userdata/workflows%2Ft9.json") not in fake.userdata_calls


async def test_api_format_is_refused_and_nothing_is_written():
    fake = UserdataComfyUI()
    error = error_of(await call(fake, "workflow_save", {"name": "api.json", "workflow": t1()}))
    assert error["code"] == "api_format_not_saved"
    assert "empty canvas" in error["message"]
    assert fake.userdata_calls == []


@pytest.mark.parametrize("workflow", [{}, {"nodes": []}, {"workflow": UI}, {"prompt": t1()}])
async def test_something_that_isnt_a_ui_workflow_is_refused(workflow):
    fake = UserdataComfyUI()
    error = error_of(await call(fake, "workflow_save", {"name": "x.json", "workflow": workflow}))
    assert error["code"] == "invalid_workflow"
    assert fake.userdata_calls == []


async def test_writes_are_capped(monkeypatch):
    monkeypatch.setattr(ts, "MAX_SAVED_BYTES", 100)
    fake = UserdataComfyUI()
    error = error_of(await call(fake, "workflow_save", {"name": "x.json", "workflow": UI}))
    assert error["code"] == "saved_workflow_too_large" and error["size_bytes"] > 100
    assert fake.userdata_calls == []


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (403, "invalid_workflow_name", False),
        (400, "save_failed", False),
        (500, "comfyui_http_error", True),
    ],
)
async def test_comfyuis_userdata_errors_map_to_codes(status, code, retryable):
    fake = UserdataComfyUI()
    fake.userdata_status = status
    error = error_of(await call(fake, "workflow_save", {"name": "x.json", "workflow": UI}))
    assert (error["code"], error["retryable"], error["status"]) == (code, retryable, status)
    if status != 400:
        error = error_of(await call(fake, "workflow_get_saved", {"name": "x.json"}))
        assert (error["code"], error["status"]) == (code, status)


async def test_save_is_the_run_profiles_and_the_readers_are_reads():
    server, _ = build_server(settings(profiles=("read",)), comfyui=UserdataComfyUI().client())
    async with Client(server, mode="legacy") as client:
        tools = {t.name: t.annotations for t in (await client.list_tools()).tools}
    assert {"workflow_list_saved", "workflow_get_saved"} <= tools.keys() and "workflow_save" not in tools
    assert all(tools[n].read_only_hint for n in ("workflow_list_saved", "workflow_get_saved"))
    server, _ = build_server(settings(profiles=("run",)), comfyui=UserdataComfyUI().client())
    async with Client(server, mode="legacy") as client:
        tools = {t.name: t.annotations for t in (await client.list_tools()).tools}
    assert "workflow_save" in tools and "workflow_get_saved" not in tools
    save = tools["workflow_save"]
    assert (save.read_only_hint, save.destructive_hint, save.idempotent_hint) == (False, True, True)


# -- workflow_validate and workflow_run by name ----------------------------------------------


async def test_validate_and_run_take_a_saved_workflow_by_name():
    fake = UserdataComfyUI({"workflows/t1.json": js_stringify(t1())})
    checked = (await call(fake, "workflow_validate", {"saved": "t1.json"})).structured_content
    assert checked["valid"] is True and checked["node_count"] == 4
    started = await call(fake, "workflow_run", {"saved": "t1.json"})
    assert not started.is_error, started.content[0].text
    [posted] = fake.posted("/prompt")
    assert posted["prompt"] == t1()


@pytest.mark.parametrize("args", [{}, {"workflow": {"1": {}}, "saved": "t1.json"}])
async def test_validate_and_run_need_exactly_one_of_workflow_and_saved(args):
    fake = UserdataComfyUI({"workflows/t1.json": js_stringify(t1())})
    for tool in ("workflow_validate", "workflow_run"):
        assert error_of(await call(fake, tool, args))["code"] == "invalid_arguments"
    assert fake.posted("/prompt") == []


async def test_run_of_an_unknown_saved_workflow_submits_nothing():
    fake = UserdataComfyUI()
    error = error_of(await call(fake, "workflow_run", {"saved": "nope.json"}))
    assert error["code"] == "unknown_saved_workflow"
    assert fake.posted("/prompt") == []
