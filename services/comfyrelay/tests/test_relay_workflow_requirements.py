"""workflow_validate's requirements report (#213): what an instance lacks to run any workflow, UI or API format,
against a fake ComfyUI. The real-ComfyUI counterpart is test_relay_requirements_live.py."""

from __future__ import annotations

import asyncio
import json

import comfyrelay.requirements as req
import httpx2
import pytest
from comfyrelay.comfyui import ComfyUIClient
from comfyrelay.server import build_server
from mcp import Client
from relay_helpers import SYSTEM_STATS, node_spec, settings

pytestmark = pytest.mark.anyio

SD15 = "v1-5-pruned-emaonly-fp16.safetensors"
SHA = "a40cf52c4779454451c4480c95947045e3f31c94"


def combo(*options: str, **extra: object) -> list:
    return [list(options), dict(extra)]


# /object_info as v0.38.0 shapes the loaders: each file input a COMBO of what ComfyUI lists for its folder, VAELoader's
# with the approximate decoders added, LoadVideo's in the V3 form.
INFO = {
    "CheckpointLoaderSimple": node_spec(
        ("MODEL", "CLIP", "VAE"), input={"required": {"ckpt_name": combo(f"sd15/{SD15}", "dreamshaper_8.safetensors")}}
    ),
    "LoraLoader": node_spec(("MODEL", "CLIP"), input={"required": {"lora_name": combo("style/detail.safetensors")}}),
    "VAELoader": node_spec(("VAE",), input={"required": {"vae_name": combo("pixel_space", "taesd")}}),
    "KSampler": node_spec(("LATENT",), input={"required": {"sampler_name": combo("euler", "euler_ancestral")}}),
    "LoadImage": node_spec(("IMAGE", "MASK"), input={"required": {"image": combo("photo.png", image_upload=True)}}),
    "LoadVideo": node_spec(
        ("VIDEO",), input={"required": {"file": ["COMBO", {"options": ["clip.mp4"], "video_upload": True}]}}
    ),
    "ImageInvert": node_spec(("IMAGE",), display_name="Invert Image"),
    "SaveImage": node_spec(("IMAGE",), output_node=True),
}
FOLDERS = {
    "checkpoints": [f"sd15/{SD15}", "dreamshaper_8.safetensors"],
    "loras": ["style/detail.safetensors"],
    "vae": [],
    "upscale_models": [],
    "custom_nodes": ["style/detail.safetensors"],  # not a model folder: never matched
}


class Fake:
    """ComfyUI's /object_info, /models and /models/<folder>; `fail` maps a path to the status it answers with."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail: dict[str, int] = {}

    def client(self) -> ComfyUIClient:
        return ComfyUIClient("http://comfyui.test:8188", transport=httpx2.MockTransport(self.handle))

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        self.calls.append(path)
        if path in self.fail:
            return httpx2.Response(self.fail[path])
        if path == "/system_stats":
            return httpx2.Response(200, json=SYSTEM_STATS)
        if path == "/object_info":
            return httpx2.Response(200, json=INFO)
        if path == "/models":
            return httpx2.Response(200, json=list(FOLDERS))
        if path.startswith("/models/") and path.removeprefix("/models/") in FOLDERS:
            return httpx2.Response(200, json=FOLDERS[path.removeprefix("/models/")])
        return httpx2.Response(404)


class FakeConverter:
    def __init__(self, result: dict) -> None:
        self.result = result

    async def convert(self, workflow):
        return self.result

    def status(self):
        return {"state": "running", "pages": 1, "conversions": 0}


async def validate(graph: dict, fake: Fake | None = None, converter: FakeConverter | None = None) -> dict:
    server, relay = build_server(settings(), comfyui=(fake or Fake()).client())
    relay.converter = converter
    async with Client(server, mode="legacy") as client:
        result = await client.call_tool("workflow_validate", {"workflow": graph})
    assert not result.is_error, result.content[0].text
    return result.structured_content


def api_graph() -> dict:
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5-prunned-emaonly-fp16.safetensors"}},
        "2": {"class_type": "LoraLoader", "inputs": {"lora_name": "detail.safetensors", "model": ["1", 0]}},
        "3": {"class_type": "KSampler", "inputs": {"sampler_name": "eular", "model": ["2", 0]}},
        "4": {"class_type": "LoadImage", "inputs": {"image": "missing.png"}},
        "5": {"class_type": "ImageInvertt", "inputs": {"image": ["4", 0]}},
        "6": {"class_type": "SaveImage", "inputs": {"images": ["5", 0], "filename_prefix": "x"}},
        "7": {"class_type": "VAELoader", "inputs": {"vae_name": "vae-ft-mse.safetensors"}},
        "8": {"class_type": "LoadVideo", "inputs": {"file": "clip.mp4"}},
    }


# -- API format -------------------------------------------------------------------


async def test_an_api_graph_lists_a_missing_node_class_with_close_names():
    got = (await validate(api_graph()))["requirements"]
    assert got["format"] == "api" and got["satisfied"] is False
    assert got["missing_nodes"] == [{"class_type": "ImageInvertt", "count": 1, "suggestions": ["ImageInvert"]}]


async def test_an_api_graph_lists_a_missing_model_with_its_folder_and_close_names():
    [ckpt, vae] = (await validate(api_graph()))["requirements"]["missing_models"]
    assert ckpt == {
        "name": "v1-5-prunned-emaonly-fp16.safetensors",
        "directory": "checkpoints",  # the one folder whose listing is the loader's options
        "node_id": "1",
        "class_type": "CheckpointLoaderSimple",
        "input": "ckpt_name",
        "suggestions": [f"sd15/{SD15}"],
    }
    # VAELoader lists no files, only approximate decoders: no folder can be told from that, and nothing is close.
    assert vae == {"name": "vae-ft-mse.safetensors", "node_id": "7", "class_type": "VAELoader", "input": "vae_name"}


async def test_an_api_graph_reports_a_model_under_another_path_with_found_at():
    [moved] = (await validate(api_graph()))["requirements"]["models_need_value_change"]
    assert moved == {
        "name": "detail.safetensors",
        "directory": "loras",
        "found_at": "style/detail.safetensors",
        "needs_value_change": "set the loader's value from 'detail.safetensors' to 'style/detail.safetensors'",
        "node_id": "2",
        "class_type": "LoraLoader",
        "input": "lora_name",
    }


async def test_an_api_graph_lists_the_input_files_the_input_directory_lacks():
    got = (await validate(api_graph()))["requirements"]
    assert got["missing_inputs"] == [
        {"class_type": "LoadImage", "input": "image", "file": "missing.png", "node_id": "4"}
    ]


async def test_values_that_are_not_files_are_left_to_comfyui():
    """sampler_name 'eular' isn't among its options either, but it names no file: ComfyUI checks it at /prompt."""
    got = await validate(api_graph())
    names = json.dumps(got["requirements"])
    assert "eular" not in names
    assert got["valid"] is False  # the unknown class, and only that, as before
    assert [e["type"] for e in got["errors"]] == ["missing_node_type"]


async def test_a_graph_with_everything_present_is_satisfied_and_lists_no_folders():
    fake = Fake()
    graph = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": f"sd15/{SD15}"}},
        "4": {"class_type": "LoadImage", "inputs": {"image": "photo.png"}},
        "6": {"class_type": "SaveImage", "inputs": {"images": ["4", 0], "filename_prefix": "x"}},
    }
    got = await validate(graph, fake)
    assert got["requirements"] == {
        "format": "api",
        "satisfied": True,
        "missing_nodes": [],
        "missing_models": [],
        "models_need_value_change": [],
        "missing_inputs": [],
    }
    assert fake.calls == ["/object_info"]  # nothing missing, so no folder is listed


async def test_proposals_need_a_source_so_an_api_graph_gets_none():
    assert "proposals" not in (await validate(api_graph()))["requirements"]


# -- UI format --------------------------------------------------------------------


def ui_graph() -> dict:
    def node(i, kind, props=None, mode=0, widgets=None):
        return {"id": i, "type": kind, "mode": mode, "properties": props or {}, "widgets_values": widgets or []}

    return {
        "nodes": [
            node(
                1,
                "CheckpointLoaderSimple",
                {
                    "cnr_id": "comfy-core",
                    "models": [
                        {
                            "name": SD15,
                            "directory": "checkpoints",
                            "url": f"https://huggingface.co/x/y/resolve/main/{SD15}",
                        },
                        {
                            "name": "flux1-dev-fp8.safetensors",
                            "directory": "checkpoints",
                            "url": "https://huggingface.co/Comfy-Org/flux1-dev/resolve/abc123/flux1-dev-fp8.safetensors?download=true",
                        },
                        {
                            "name": "4x-Ultra.pth",
                            "directory": "upscale_models",
                            "url": "https://example.com/files/4x-UltraSharp.pth",
                        },
                    ],
                },
                widgets=[SD15],
            ),
            node(2, "MathExpression|pysssss", {"cnr_id": "comfyui-custom-scripts", "ver": "1.2.5"}),
            node(3, "MathExpression|pysssss", {"cnr_id": "comfyui-custom-scripts", "ver": "1.2.5"}),
            node(4, "ImageResizeKJv2", {"aux_id": "kijai/ComfyUI-KJNodes", "ver": SHA}),
            node(5, "WanVideoSampler", {"cnr_id": "ComfyUI-WanVideoWrapper", "ver": "nightly"}),
            node(6, "NewCoreNode", {"cnr_id": "comfy-core", "ver": "0.39.0"}),
            node(7, "LoadImage", {"cnr_id": "comfy-core"}, widgets=["missing.png", "image"]),
            node(8, "NotInstalledButMuted", {"cnr_id": "some-pack", "ver": "1.0.0"}, mode=2),
            node(9, "SaveImage"),
        ],
        "links": [],
    }


async def test_a_ui_graph_names_each_missing_classs_pack_from_its_properties():
    got = (await validate(ui_graph()))["requirements"]
    assert got["format"] == "ui"
    nodes = {n["class_type"]: n for n in got["missing_nodes"]}
    assert set(nodes) == {"MathExpression|pysssss", "ImageResizeKJv2", "WanVideoSampler", "NewCoreNode"}  # not muted
    assert nodes["MathExpression|pysssss"] | {"suggestions": None} == {
        "class_type": "MathExpression|pysssss",
        "count": 2,
        "pack": "comfyui-custom-scripts",
        "version": "1.2.5",
        "suggestions": None,
    }
    assert (nodes["ImageResizeKJv2"]["aux_id"], nodes["ImageResizeKJv2"]["version"]) == ("kijai/ComfyUI-KJNodes", SHA)


async def test_a_ui_graph_lists_declared_models_with_folder_and_source_and_found_at():
    got = (await validate(ui_graph()))["requirements"]
    assert [(m["name"], m["directory"], m["folder_known"]) for m in got["missing_models"]] == [
        ("flux1-dev-fp8.safetensors", "checkpoints", True),
        ("4x-Ultra.pth", "upscale_models", True),
    ]
    assert got["missing_models"][0]["url"].startswith("https://huggingface.co/Comfy-Org/flux1-dev/")
    [moved] = got["models_need_value_change"]
    assert (moved["name"], moved["directory"], moved["found_at"]) == (SD15, "checkpoints", f"sd15/{SD15}")
    assert got["missing_inputs"] == [{"class_type": "LoadImage", "input": "image", "file": "missing.png"}]


async def test_a_ui_graph_gets_proposals_for_a_human_to_apply():
    proposals = (await validate(ui_graph()))["requirements"]["proposals"]
    assert "nothing here installs or downloads" in proposals["note"]
    assert proposals["comfy_yaml_models"] == [
        {
            "name": "flux1-dev-fp8",
            "files": [
                {
                    "source": "hf:Comfy-Org/flux1-dev",
                    "file": "flux1-dev-fp8.safetensors",
                    "install": "models/checkpoints/",
                    "revision": "abc123",
                }
            ],
        },
        {
            "name": "4x-ultra",
            "files": [
                {
                    "source": "https://example.com/files/4x-UltraSharp.pth",
                    "sha256": "<the file's SHA256>",
                    "as": "4x-Ultra.pth",
                    "install": "models/upscale_models/",
                }
            ],
        },
    ]
    # A registry pack at its release; one at nightly can't be pinned; a git pack at its commit; ComfyUI's own
    # (comfy-core) needs a newer ComfyUI, not a pack.
    assert proposals["custom_nodes"] == {
        "git_custom_nodes": {"https://github.com/kijai/ComfyUI-KJNodes": {"disabled": False, "hash": SHA}},
        "cnr_custom_nodes": {"comfyui-custom-scripts": "1.2.5", "ComfyUI-WanVideoWrapper": "<a released version>"},
    }


async def test_a_ui_graph_is_reported_where_this_server_does_not_convert():
    got = await validate(ui_graph())
    assert got["valid"] is False and got["errors"][0]["type"] == "invalid_workflow"  # as before
    assert got["requirements"]["satisfied"] is False


async def test_a_converted_ui_graph_also_finds_models_named_only_in_widget_values():
    converted = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": SD15}},  # declared: not repeated
        "2": {"class_type": "LoraLoader", "inputs": {"lora_name": "undeclared.safetensors", "model": ["1", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "x"}},
    }
    got = (await validate(ui_graph(), converter=FakeConverter(converted)))["requirements"]
    assert got["format"] == "ui"
    assert [m["name"] for m in got["missing_models"]] == [
        "flux1-dev-fp8.safetensors",
        "4x-Ultra.pth",
        "undeclared.safetensors",
    ]
    assert got["missing_models"][-1]["directory"] == "loras"
    assert [m["name"] for m in got["models_need_value_change"]] == [SD15]
    assert len(got["missing_nodes"]) == 4  # the UI graph's, with their packs


# -- optional detail: never the call's failure ----------------------------------------


async def test_a_folder_that_cant_be_listed_is_noted_and_its_models_left_unchecked():
    fake = Fake()
    fake.fail["/models/checkpoints"] = 500
    got = (await validate(ui_graph(), fake))["requirements"]
    assert [m["name"] for m in got["missing_models"]] == ["4x-Ultra.pth"]
    assert got["models_need_value_change"] == []
    [note] = got["notes"]
    assert "'checkpoints'" in note and "comfyui_http_error" in note


async def test_an_api_graphs_folders_that_cant_be_listed_leave_only_the_folder_out():
    fake = Fake()
    fake.fail["/models"] = 500
    [ckpt, _] = (await validate(api_graph(), fake))["requirements"]["missing_models"]
    assert "directory" not in ckpt and ckpt["suggestions"] == [f"sd15/{SD15}"]


async def test_a_report_that_fails_leaves_validate_as_it_was(monkeypatch):
    async def broken(*args):
        raise ValueError("a shape nothing expects")

    monkeypatch.setattr(req, "_report", broken)
    got = await validate(api_graph())
    assert (got["requirements"], got["requirements_unchecked"]) == (None, "check_failed")
    assert got["valid"] is False and [e["type"] for e in got["errors"]] == ["missing_node_type"]


async def test_a_report_that_takes_too_long_is_left_out(monkeypatch):
    async def slow(*args):
        await asyncio.sleep(5)

    monkeypatch.setattr(req, "_report", slow)
    monkeypatch.setattr(req, "REQUIREMENTS_SECONDS", 0.05)
    got = await validate(api_graph())
    assert (got["requirements"], got["requirements_unchecked"]) == (None, "timeout")


async def test_a_graph_it_cant_read_says_so():
    got = await validate({"prompt": {"1": {"class_type": "SaveImage", "inputs": {}}}})
    assert (got["requirements"], got["requirements_unchecked"]) == (None, "invalid_workflow")


async def test_every_list_is_capped(monkeypatch):
    monkeypatch.setattr(req, "MAX_ITEMS", 3)
    graph = {str(i): {"class_type": f"Missing{i}", "inputs": {}} for i in range(10)}
    got = (await validate(graph))["requirements"]
    assert len(got["missing_nodes"]) == 3 and got["truncated"] is True
