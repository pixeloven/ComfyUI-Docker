"""workflow_validate's requirements report (#213) against a real, booted ComfyUI. Skipped unless
COMFYRELAY_LIVE_COMFYUI_URL names one, as test_relay_workflow_live.py is:

    cd services
    COMFYRELAY_LIVE_COMFYUI_URL=http://127.0.0.1:8188 \
      uv run --locked pytest -q comfyrelay/tests/test_relay_requirements_live.py

It reads only: nothing is submitted, uploaded or written. It needs no model, and assumes the instance hasn't got
the ones it names.
"""

from __future__ import annotations

import os

import httpx2
import pytest
from comfyrelay.comfyui import ComfyUIClient
from comfyrelay.server import build_server
from mcp import Client
from relay_helpers import settings

URL = os.environ.get("COMFYRELAY_LIVE_COMFYUI_URL", "")
pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not URL, reason="COMFYRELAY_LIVE_COMFYUI_URL is not set"),
]

ABSENT = "relay-requirements-absent-model.safetensors"


@pytest.fixture
async def client():
    server, _ = build_server(settings(comfyui_url=URL), comfyui=ComfyUIClient(URL))
    async with Client(server, mode="legacy") as c:
        yield c


async def requirements_of(client, graph: dict) -> dict:
    result = await client.call_tool("workflow_validate", {"workflow": graph})
    assert not result.is_error, result.content[0].text
    got = result.structured_content
    assert got["requirements_unchecked"] is None, got
    return got["requirements"]


async def test_an_api_graph_reports_what_this_instance_lacks(client):
    graph = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ABSENT}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "relay-requirements-absent.png"}},
        "3": {"class_type": "ImageInvertt", "inputs": {"image": ["2", 0]}},
        "4": {
            "class_type": "KSampler",
            "inputs": {"sampler_name": "eular", "model": ["1", 0]},
        },
        "5": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "never_"}},
    }
    got = await requirements_of(client, graph)
    assert got["format"] == "api" and got["satisfied"] is False
    [node] = got["missing_nodes"]
    assert node["class_type"] == "ImageInvertt" and "ImageInvert" in node["suggestions"]
    [model] = got["missing_models"]
    assert (model["name"], model["node_id"], model["class_type"], model["input"]) == (
        ABSENT,
        "1",
        "CheckpointLoaderSimple",
        "ckpt_name",
    )
    assert got["missing_inputs"] == [
        {"class_type": "LoadImage", "input": "image", "file": "relay-requirements-absent.png", "node_id": "2"}
    ]
    assert "eular" not in str(got)  # a value, not a requirement: ComfyUI checks it at /prompt


async def declared_template() -> tuple[dict, dict]:
    """The first template this instance serves whose nodes declare a model it hasn't got on disk under that name."""
    async with httpx2.AsyncClient(base_url=URL, timeout=30) as http:
        index = (await http.get("/templates/index.json")).json()
        for name in [t["name"] for c in index for t in c.get("templates") or []]:
            workflow = (await http.get(f"/templates/{name}.json")).json()
            subgraphs = (workflow.get("definitions") or {}).get("subgraphs") or []
            if subgraphs or any(n.get("mode") in (2, 4) for n in workflow.get("nodes") or []):
                continue  # one whose every node runs, at the top level: what declares a model is what it checks
            for node in workflow.get("nodes") or []:
                for model in (node.get("properties") or {}).get("models") or []:
                    listed = await http.get(f"/models/{model['directory']}")
                    on_disk = listed.json() if listed.status_code == 200 else []
                    if model["name"] not in on_disk and model.get("url", "").startswith("https://huggingface.co/"):
                        return workflow, model
    pytest.fail("no template without subgraphs declares a Hugging Face model this instance lacks")


async def test_a_ui_graph_reports_its_declared_models_with_their_source(client):
    workflow, declared = await declared_template()
    got = await requirements_of(client, workflow)
    assert got["format"] == "ui"
    missing = {m["name"]: m for m in got["missing_models"]}
    moved = {m["name"] for m in got["models_need_value_change"]}
    assert declared["name"] in missing or declared["name"] in moved
    if declared["name"] in missing:
        model = missing[declared["name"]]
        assert (model["directory"], model["url"]) == (declared["directory"], declared["url"])
        files = [f for e in got["proposals"]["comfy_yaml_models"] for f in e["files"]]
        assert any(f["install"] == f"models/{declared['directory']}/" for f in files)


async def template_checkpoint() -> tuple[str, set[str]]:
    """A checkpoint some stock template declares with a URL and this instance hasn't got, and every URL the
    templates declare for it."""
    async with httpx2.AsyncClient(base_url=URL, timeout=30) as http:
        on_disk = set((await http.get("/models/checkpoints")).json())
        index = (await http.get("/templates/index.json")).json()
        urls: dict[str, set[str]] = {}
        for name in [t["name"] for c in index for t in c.get("templates") or []]:
            workflow = (await http.get(f"/templates/{name}.json")).json()
            for node in workflow.get("nodes") or []:
                for model in (node.get("properties") or {}).get("models") or []:
                    if model.get("directory") == "checkpoints" and isinstance(model.get("url"), str):
                        urls.setdefault(model["name"], set()).add(model["url"])
    for name, found in sorted(urls.items()):
        if name not in on_disk:
            return name, found
    pytest.fail("no stock template declares a checkpoint this instance lacks")


async def test_a_bare_missing_model_takes_its_source_from_a_stock_template(client):
    name, urls = await template_checkpoint()
    graph = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": name}},
        "2": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ABSENT}},
    }
    got = await requirements_of(client, graph)
    sourced, unsourced = got["missing_models"]
    assert sourced["source"]["declared_by"] == "template" and sourced["source"]["url"] in urls
    assert unsourced["source"] is None
    assert any("1 missing model(s) have no source" in n for n in got["notes"])
    files = [f for e in got["proposals"]["comfy_yaml_models"] for f in e["files"]]
    assert [f["install"] for f in files] == ["models/checkpoints/"]


async def test_values_the_loader_resolves_itself_and_unread_widget_values_are_not_claimed(client):
    """LoadImage takes a subfolder or annotated value that its options never list; and a UI graph this server
    doesn't convert has its widget values unread, so it is never called satisfied."""
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "pasted/relay-requirements.png"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "relay-requirements.png [output]"}},
        "3": {"class_type": "PreviewImage", "inputs": {"images": ["1", 0]}},
    }
    got = await requirements_of(client, graph)
    assert got["missing_inputs"] == [] and any(n.startswith("2 input file value(s)") for n in got["notes"])
    ui = {
        "nodes": [
            {"id": 1, "type": "LoraLoader", "mode": 0, "widgets_values": [ABSENT, 1.0, 1.0]},
            {"id": 2, "type": "PreviewAny", "mode": 0},
        ],
        "links": [],
    }
    got = await requirements_of(client, ui)
    assert got["satisfied"] is None and got["missing_models"] == []
