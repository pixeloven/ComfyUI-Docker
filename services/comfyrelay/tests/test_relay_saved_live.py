"""The saved-workflow tools (#216) against a real, booted ComfyUI's /api/userdata. Skipped unless
COMFYRELAY_LIVE_COMFYUI_URL names one, as test_relay_workflow_live.py is:

    cd services
    COMFYRELAY_LIVE_COMFYUI_URL=http://127.0.0.1:8188 \\
      uv run --locked [--extra convert] pytest -q comfyrelay/tests/test_relay_saved_live.py

It writes files named relay-live-*.json into that ComfyUI's user/default/workflows and deletes them afterwards, and
runs built-in image nodes, so point it at a scratch instance. The case that runs a saved UI workflow through the
converter is in test_relay_convert_live.py, which CI runs where the convert extra is installed.
"""

from __future__ import annotations

import json
import os
import uuid
from urllib.parse import quote

import httpx2
import pytest
from comfyrelay.comfyui import ComfyUIClient
from comfyrelay.server import build_server
from mcp import Client
from relay_helpers import settings

URL = os.environ.get("COMFYRELAY_LIVE_COMFYUI_URL", "").rstrip("/")
pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not URL, reason="COMFYRELAY_LIVE_COMFYUI_URL is not set"),
]


def ui_graph(prefix: str, width: int = 64) -> dict:
    """EmptyImage into SaveImage in the editor's UI format: no model needed."""

    def node(nid, typ, order, inputs, outputs, widgets):
        return {
            "id": nid,
            "type": typ,
            "pos": [100 * nid, 100],
            "size": [315, 100],
            "flags": {},
            "order": order,
            "mode": 0,
            "inputs": [{"name": n, "type": t, "link": link} for n, t, link in inputs],
            "outputs": [{"name": n, "type": t, "links": links, "slot_index": 0} for n, t, links in outputs],
            "properties": {"Node name for S&R": typ},
            "widgets_values": widgets,
        }

    return {
        "last_node_id": 2,
        "last_link_id": 1,
        "nodes": [
            node(1, "EmptyImage", 0, [], [("IMAGE", "IMAGE", [1])], [width, 48, 1, 0x336699]),
            node(2, "SaveImage", 1, [("images", "IMAGE", 1)], [], [prefix]),
        ],
        "links": [[1, 1, 0, 2, 0, "IMAGE"]],
        "groups": [],
        "config": {},
        "extra": {"note": "café ✓"},
        "version": 0.4,
    }


def api_graph(prefix: str) -> dict:
    return {
        "1": {"class_type": "EmptyImage", "inputs": {"width": 64, "height": 48, "batch_size": 1, "color": 0x996633}},
        "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": prefix}},
    }


def error_of(result) -> dict:
    assert result.is_error, result.structured_content
    text = result.content[0].text
    return json.loads(text[text.index("{") :])["error"]


def userdata(name: str) -> str:
    return "/api/userdata/" + quote(f"workflows/{name}", safe="")


@pytest.fixture
async def names():
    """Unique file names, deleted from ComfyUI afterwards."""
    made: list[str] = []

    def make(stem: str = "wf") -> str:
        made.append(f"relay-live-{stem}-{uuid.uuid4().hex[:8]}.json")
        return made[-1]

    yield make
    async with httpx2.AsyncClient(base_url=URL, timeout=10) as http:
        for name in made:
            await http.delete(userdata(name))


async def raw(name: str) -> bytes | None:
    async with httpx2.AsyncClient(base_url=URL, timeout=10) as http:
        r = await http.get(userdata(name))
    return r.content if r.status_code == 200 else None


@pytest.fixture
async def client():
    server, _ = build_server(settings(comfyui_url=URL), comfyui=ComfyUIClient(URL))
    async with Client(server, mode="legacy") as c:
        yield c


async def test_save_list_get_and_overwrite(client, names):
    name = names()
    ui = ui_graph("relay_live_saved_")
    saved = await client.call_tool("workflow_save", {"name": name, "workflow": ui})
    assert saved.structured_content == {
        "name": name,
        "written": True,
        "replaced": False,
        "size_bytes": saved.structured_content["size_bytes"],
    }
    # As the editor writes it: JSON.stringify's compact form.
    assert await raw(name) == json.dumps(ui, separators=(",", ":"), ensure_ascii=False).encode()

    listed = (await client.call_tool("workflow_list_saved", {})).structured_content
    assert name in [w["name"] for w in listed["workflows"]]

    got = (await client.call_tool("workflow_get_saved", {"name": f"workflows/{name}"})).structured_content
    assert (got["name"], got["format"], got["workflow"]) == (name, "ui", ui)

    edited = ui_graph("relay_live_edited_", width=96)
    error = error_of(await client.call_tool("workflow_save", {"name": name, "workflow": edited}))
    assert error["code"] == "workflow_exists" and "overwrite" in error["message"]
    assert json.loads(await raw(name)) == ui

    replaced = await client.call_tool("workflow_save", {"name": name, "workflow": edited, "overwrite": True})
    assert (replaced.structured_content["written"], replaced.structured_content["replaced"]) == (True, True)
    assert json.loads(await raw(name)) == edited


async def test_an_unedited_round_trip_keeps_the_bytes(client, names):
    """A file another tool wrote, pretty-printed, read and saved back unchanged, isn't rewritten."""
    name = names("pretty")
    held = json.dumps(ui_graph("relay_live_pretty_"), indent=2).encode()
    async with httpx2.AsyncClient(base_url=URL, timeout=10) as http:
        assert (await http.post(userdata(name), content=held)).status_code == 200
    read = (await client.call_tool("workflow_get_saved", {"name": name})).structured_content["workflow"]
    again = await client.call_tool("workflow_save", {"name": name, "workflow": read, "overwrite": True})
    assert again.structured_content["written"] is False
    assert await raw(name) == held


async def test_api_format_and_bad_names_are_refused(client, names):
    name = names("api")
    error = error_of(await client.call_tool("workflow_save", {"name": name, "workflow": api_graph("x")}))
    assert error["code"] == "api_format_not_saved"
    assert await raw(name) is None
    for bad in ("../comfy.settings.json", "a/../../x.json", "/x.json", "..%2Fx.json", "a\\b.json"):
        error = error_of(await client.call_tool("workflow_get_saved", {"name": bad}))
        assert error["code"] == "invalid_workflow_name", bad
    error = error_of(await client.call_tool("workflow_get_saved", {"name": names("absent")}))
    assert error["code"] == "unknown_saved_workflow"


async def test_run_and_validate_take_a_saved_api_graph_by_name(client, names):
    """An API-format file put there some other way (this server won't save one) still runs by name."""
    name = names("run")
    async with httpx2.AsyncClient(base_url=URL, timeout=10) as http:
        assert (
            await http.post(userdata(name), content=json.dumps(api_graph("relay_live_saved_run_")))
        ).status_code == 200
    checked = (await client.call_tool("workflow_validate", {"saved": name})).structured_content
    assert checked["runnable"] is True, checked
    started = await client.call_tool("workflow_run", {"saved": name})
    assert not started.is_error, started.content[0].text
    done = await client.call_tool("job_status", {"job_id": started.structured_content["job_id"], "timeout_seconds": 60})
    assert done.structured_content["state"] == "succeeded", done.structured_content
    [file] = done.structured_content["result"]["files"]
    assert file["filename"].startswith("relay_live_saved_run_")
