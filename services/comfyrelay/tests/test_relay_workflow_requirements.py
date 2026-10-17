"""workflow_validate's requirements report (#213): what an instance lacks to run any workflow, UI or API format,
against a fake ComfyUI. The real-ComfyUI counterpart is test_relay_requirements_live.py."""

from __future__ import annotations

import asyncio
import json
import time

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
    "UpscaleModelLoader": node_spec(("UPSCALE_MODEL",), input={"required": {"model_name": combo()}}),
    "ImageInvert": node_spec(("IMAGE",), display_name="Invert Image"),
    "SaveImage": node_spec(("IMAGE",), output_node=True),
}
FOLDERS = {
    "checkpoints": [f"sd15/{SD15}", "dreamshaper_8.safetensors"],
    "loras": ["style/detail.safetensors"],
    "vae": [],
    "upscale_models": [],
    "custom_nodes": ["style/detail.safetensors"],  # not a model folder: never matched
    "configs": ["v1-inference.yaml"],  # nor these two: never listed
    "datasets": [],
}


class Fake:
    """ComfyUI's /object_info, /models and /models/<folder>, and, given `templates` (name -> workflow), the
    templates it serves; `fail` maps a path to the status it answers with, `delays` to seconds it waits first."""

    def __init__(self, info: dict | None = None, folders: dict | None = None, templates: dict | None = None) -> None:
        self.calls: list[str] = []
        self.fail: dict[str, int] = {}
        self.delays: dict[str, float] = {}
        self.info = INFO if info is None else info
        self.folders = FOLDERS if folders is None else folders
        self.templates = templates

    def client(self) -> ComfyUIClient:
        return ComfyUIClient("http://comfyui.test:8188", transport=httpx2.MockTransport(self.handle))

    async def handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        self.calls.append(path)
        await asyncio.sleep(self.delays.get(path, 0))
        if path in self.fail:
            return httpx2.Response(self.fail[path])
        if path == "/system_stats":
            stats = {**SYSTEM_STATS, "system": {**SYSTEM_STATS["system"], "installed_templates_version": "0.1.0"}}
            return httpx2.Response(200, json=stats)
        if self.templates is not None and path == "/templates/index.json":
            entries = [{"name": n, "title": n, "tags": []} for n in self.templates]
            return httpx2.Response(200, json=[{"category": "c", "title": "t", "templates": entries}])
        if self.templates is not None and path.removeprefix("/templates/").removesuffix(".json") in self.templates:
            return httpx2.Response(200, json=self.templates[path.removeprefix("/templates/").removesuffix(".json")])
        if path == "/object_info":
            return httpx2.Response(200, json=self.info)
        if path == "/models":
            return httpx2.Response(200, json=list(self.folders))
        if path.startswith("/models/") and path.removeprefix("/models/") in self.folders:
            return httpx2.Response(200, json=self.folders[path.removeprefix("/models/")])
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
        "source": None,  # always present: the workflow declares none, and (no template cache here) nothing else was
    }
    # VAELoader lists no files, only approximate decoders: no folder can be told from that, and nothing is close.
    assert vae == {
        "name": "vae-ft-mse.safetensors",
        "node_id": "7",
        "class_type": "VAELoader",
        "input": "vae_name",
        "source": None,
    }


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
                    ],
                },
                widgets=[SD15],
            ),
            node(
                12,
                "CheckpointLoaderSimple",
                {
                    "cnr_id": "comfy-core",
                    "models": [
                        {
                            "name": "flux1-dev-fp8.safetensors",
                            "directory": "checkpoints",
                            "url": "https://huggingface.co/Comfy-Org/flux1-dev/resolve/abc123/flux1-dev-fp8.safetensors?download=true",
                        },
                    ],
                },
                widgets=["flux1-dev-fp8.safetensors"],
            ),
            node(
                13,
                "UpscaleModelLoader",
                {
                    "cnr_id": "comfy-core",
                    "models": [
                        {
                            "name": "4x-Ultra.pth",
                            "directory": "upscale_models",
                            "url": "https://example.com/files/4x-UltraSharp.pth",
                        },
                    ],
                },
                widgets=["4x-Ultra.pth"],
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
    assert req.UNCONVERTED_NOTE in got["requirements"]["notes"]


async def test_an_unconverted_ui_graph_with_nothing_declared_missing_is_never_satisfied():
    """Its widget values weren't read, so a model named only there may be missing: satisfied is null, not true."""
    graph = {
        "nodes": [
            {"id": 1, "type": "LoraLoader", "mode": 0, "widgets_values": ["undeclared.safetensors", 1.0, 1.0]},
            {"id": 2, "type": "SaveImage", "mode": 0},
        ],
        "links": [],
    }
    got = (await validate(graph))["requirements"]
    assert got["satisfied"] is None and got["missing_models"] == []
    assert got["notes"] == [req.UNCONVERTED_NOTE]
    converted = {"1": {"class_type": "LoraLoader", "inputs": {"lora_name": "style/detail.safetensors"}}}
    assert (await validate(graph, converter=FakeConverter(converted)))["requirements"]["satisfied"] is True


async def test_a_missing_core_node_says_a_newer_comfyui_may_be_needed():
    nodes = {n["class_type"]: n for n in (await validate(ui_graph()))["requirements"]["missing_nodes"]}
    assert "newer ComfyUI" in nodes["NewCoreNode"]["hint"] and "0.39.0" in nodes["NewCoreNode"]["hint"]
    assert "hint" not in nodes["MathExpression|pysssss"]


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
    [note] = [n for n in got["notes"] if "'checkpoints'" in n]
    assert "comfyui_http_error" in note


async def test_nothing_listed_is_not_satisfied_when_a_declared_models_folder_went_unlisted():
    """A converted UI graph with nothing missing, but whose declared model's folder couldn't be listed: that model
    wasn't checked, so satisfied is null, not true."""
    graph = {
        "nodes": [
            {
                "id": 1,
                "type": "CheckpointLoaderSimple",
                "mode": 0,
                "properties": {"models": [{"name": "declared.safetensors", "directory": "checkpoints"}]},
            }
        ],
        "links": [],
    }
    converted = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": f"sd15/{SD15}"}}}
    fake = Fake()
    assert (await validate(graph, fake, FakeConverter(converted)))["requirements"]["satisfied"] is False  # control
    fake = Fake()
    fake.fail["/models/checkpoints"] = 500
    got = (await validate(graph, fake, FakeConverter(converted)))["requirements"]
    assert got["missing_models"] == [] and got["satisfied"] is None
    assert any("couldn't be listed" in n for n in got["notes"])


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


async def test_proposals_are_capped_like_the_lists(monkeypatch):
    monkeypatch.setattr(req, "MAX_ITEMS", 3)
    graph = {
        "nodes": [
            {
                "id": i,
                "type": f"Pack{i}Node",
                "mode": 0,
                "properties": {
                    "cnr_id": f"pack-{i}",
                    "ver": "1.0.0",
                    "models": [
                        {
                            "name": f"m{i}.safetensors",
                            "directory": "loras",
                            "url": f"https://huggingface.co/o/r/resolve/main/m{i}.safetensors",
                        }
                    ],
                },
            }
            for i in range(10)
        ],
        "links": [],
    }
    got = (await validate(graph))["requirements"]
    assert got["truncated"] is True
    assert len(got["missing_nodes"]) == len(got["missing_models"]) == 3
    assert len(got["proposals"]["comfy_yaml_models"]) == 3
    assert len(got["proposals"]["custom_nodes"]["cnr_custom_nodes"]) == 3


# -- input files the loader resolves itself ----------------------------------------------


async def test_a_loader_value_in_a_subfolder_or_annotated_is_not_reported_missing():
    """LoadImage validates its own value (VALIDATE_INPUTS): it takes pasted/x.png, x.png [output] and the like,
    which its options never list, so they are noted as unchecked rather than reported missing."""
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "pasted/image.png"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "x.png [output]"}},
        "3": {"class_type": "LoadImage", "inputs": {"image": "clipspace/a.png [input]"}},
        "4": {"class_type": "LoadImage", "inputs": {"image": "gone.png"}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "x"}},
    }
    got = (await validate(graph))["requirements"]
    assert [i["file"] for i in got["missing_inputs"]] == ["gone.png"]
    assert any(n.startswith("3 input file value(s)") for n in got["notes"])
    ui = {
        "nodes": [{"id": 1, "type": "LoadImage", "mode": 0, "widgets_values": ["pasted/image.png", "image"]}],
        "links": [],
    }
    got = (await validate(ui))["requirements"]
    assert got["missing_inputs"] == [] and any(n.startswith("1 input file value(s)") for n in got["notes"])


async def test_nothing_listed_is_not_satisfied_when_an_input_value_went_unchecked():
    """An API graph with nothing missing but a LoadImage value the loader resolves itself: null, not true."""
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "photo.png"}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "x"}},
    }
    assert (await validate(graph))["requirements"]["satisfied"] is True  # control
    graph["1"]["inputs"]["image"] = "pasted/photo.png"
    got = (await validate(graph))["requirements"]
    assert got["missing_inputs"] == [] and got["satisfied"] is None
    assert got["notes"] == [req._input_note(1)]


# -- found_at, folders and proposals --------------------------------------------------


async def test_several_files_of_that_name_are_reported_as_candidates():
    loras = ["a/x.safetensors", "b/x.safetensors"]
    info = {**INFO, "LoraLoader": node_spec(("MODEL",), input={"required": {"lora_name": combo(*loras)}})}
    graph = {"1": {"class_type": "LoraLoader", "inputs": {"lora_name": "x.safetensors"}}}
    [moved] = (await validate(graph, Fake(info, {**FOLDERS, "loras": loras})))["requirements"][
        "models_need_value_change"
    ]
    assert "found_at" not in moved
    assert moved["candidates"] == loras and moved["directory"] == "loras"
    assert moved["needs_value_change"].startswith("2 files are named 'x.safetensors'")


async def test_folder_listings_are_reused_and_skip_folders_that_hold_no_models():
    fake = Fake()
    server, _ = build_server(settings(), comfyui=fake.client())
    async with Client(server, mode="legacy") as client:
        for _ in range(2):
            await client.call_tool("workflow_validate", {"workflow": api_graph()})
    assert fake.calls.count("/models") == 1 and fake.calls.count("/models/checkpoints") == 1
    assert not {"/models/configs", "/models/datasets", "/models/custom_nodes"} & set(fake.calls)


async def test_model_proposals_decode_civitai_and_unknown_folders():
    def model(name, directory, url):
        return {"name": name, "directory": directory, "url": url}

    long_path = "a" * 480
    hf = "https://huggingface.co/o/r/resolve"
    graph = {
        "nodes": [
            {
                "id": 1,
                "type": "LoraLoader",
                "mode": 0,
                "properties": {
                    "models": [
                        model("my lora.safetensors", "loras", f"{hf}/v%201/sub/my%20lora.safetensors"),
                        model("cv.safetensors", "loras", "https://civitai.com/api/download/models/12345?type=Model"),
                        model("x.safetensors", "no_such_folder", f"{hf}/main/x.safetensors"),
                        model("long.safetensors", "loras", f"{hf}/main/{long_path}/long.safetensors"),
                    ]
                },
            }
        ],
        "links": [],
    }
    got = (await validate(graph))["requirements"]
    names = ["my lora.safetensors", "cv.safetensors", "x.safetensors", "long.safetensors"]
    assert [m["name"] for m in got["missing_models"]] == names
    assert got["missing_models"][-1]["url"].endswith("…")  # shown capped
    entries = got["proposals"]["comfy_yaml_models"]
    assert entries[0]["files"] == [
        {"source": "hf:o/r", "file": "sub/my lora.safetensors", "install": "models/loras/", "revision": "v 1"}
    ]
    assert entries[1]["files"] == [{"source": "civitai:12345", "as": "cv.safetensors", "install": "models/loras/"}]
    # Parsed from the full URL, not the capped one shown: the path fits once the host and revision are gone.
    assert entries[2]["files"][0]["file"] == f"{long_path}/long.safetensors"
    assert len(entries) == 3  # none for the folder this ComfyUI hasn't got: a note says so
    assert any("'no_such_folder'" in n for n in got["notes"])


# -- suggestions: bounded, and never outliving the call ---------------------------------


def huge_loras(n: int) -> Fake:
    files = [f"set{i % 50}/lora_{i:06d}_detail_style.safetensors" for i in range(n)]
    info = {**INFO, "LoraLoader": node_spec(("MODEL",), input={"required": {"lora_name": [files, {}]}})}
    return Fake(info, {**FOLDERS, "loras": files})


def missing_loras(count: int) -> dict:
    return {
        str(i): {"class_type": "LoraLoader", "inputs": {"lora_name": f"nothing_like_{i}_anything.safetensors"}}
        for i in range(count)
    }


@pytest.fixture
def chunks(monkeypatch):
    """How many chunks the suggestion scan has compared, counted as it goes."""
    seen = [0, 0.0]  # chunks compared; seconds each one is held up, to make a scan as slow as a test needs
    real = req.heapq.nlargest

    def counting(*args, **kwargs):
        seen[0] += 1
        time.sleep(seen[1])
        return real(*args, **kwargs)

    monkeypatch.setattr(req.heapq, "nlargest", counting)
    return seen


async def test_the_suggestion_scan_stops_at_its_deadline(monkeypatch, chunks):
    monkeypatch.setattr(req, "SUGGEST_SECONDS", 0.5)
    monkeypatch.setattr(req, "SCAN_CHUNK", 50)
    chunks[1] = 0.005  # 400 chunks a model: the scan alone would take 20s
    got = (await validate(missing_loras(20), huge_loras(20_000)))["requirements"]
    assert len(got["missing_models"]) == 20
    assert any(n.startswith("suggestions stopped after") for n in got["notes"])
    before = chunks[0]
    assert before > 0, "the scan never started"
    await asyncio.sleep(0.5)
    assert chunks[0] == before, "the scan went on after the call returned"


async def test_the_suggestion_scan_stops_when_it_is_cancelled(monkeypatch, chunks):
    """The report's own bound cancels whatever step it is in; a scan cancelled mid-way stops within a chunk."""
    monkeypatch.setattr(req, "SCAN_CHUNK", 50)
    chunks[1] = 0.005  # 400 chunks a model: the scan alone would take 40s
    files = [f"set{i % 50}/lora_{i:06d}_detail_style.safetensors" for i in range(20_000)]
    models = [
        req.RequiredModel(name=f"nothing_like_{i}.safetensors", class_type="LoraLoader", input="lora_name")
        for i in range(20)
    ]
    scan = asyncio.ensure_future(req._suggest([], models, {}, {("LoraLoader", "lora_name"): files}, 60))
    await asyncio.sleep(0.5)
    scan.cancel()
    with pytest.raises(asyncio.CancelledError):
        await scan
    await asyncio.sleep(0.2)  # one chunk, at most, was in flight
    before = chunks[0]
    assert before > 0, "the scan never started"
    await asyncio.sleep(0.5)
    assert chunks[0] == before, "the scan went on after the report was cut short"


async def test_only_the_first_few_missing_values_get_suggestions():
    graph = {
        str(i): {"class_type": "LoraLoader", "inputs": {"lora_name": f"detail{i}.safetensors"}}
        for i in range(req.MAX_SUGGESTED + 5)
    }
    got = (await validate(graph))["requirements"]
    assert len([m for m in got["missing_models"] if "suggestions" in m]) == req.MAX_SUGGESTED
    assert f"the first {req.MAX_SUGGESTED} missing classes and models only" in " ".join(got["notes"])


# -- ComfyUI's data, untrusted ---------------------------------------------------------


async def test_a_malformed_object_info_entry_costs_only_its_own_detail():
    info = {**INFO, "Broken": ["not", "an", "object"], "AlsoBroken": {"input": {"required": ["x"]}}}
    graph = {
        "1": {"class_type": "ImageInvertt", "inputs": {}},
        "2": {"class_type": "AlsoBroken", "inputs": {"x": "y.safetensors"}},
        "3": {"class_type": "Broken", "inputs": {}},
    }
    report, why = await req.workflow_requirements(Fake(info).client(), graph, graph, info, False)
    assert why is None
    assert [(n.class_type, n.suggestions) for n in report.missing_nodes] == [("ImageInvertt", ["ImageInvert"])]


async def test_a_class_name_too_long_to_use_is_never_suggested():
    long_name = "ImageInvert" + "x" * 200
    info = {**INFO, long_name: node_spec(("IMAGE",))}
    got = (await validate({"1": {"class_type": "ImageInvertt", "inputs": {}}}, Fake(info)))["requirements"]
    [node] = got["missing_nodes"]
    assert node["suggestions"] == ["ImageInvert"]


# -- sources: the workflow's, else the instance's own templates ---------------------------

TURBO = "sd_xl_turbo_1.0_fp16.safetensors"
TURBO_URL = f"https://huggingface.co/stabilityai/sdxl-turbo/resolve/main/{TURBO}"


def template_declaring(name: str, directory: str, url: str, loader: str = "CheckpointLoaderSimple") -> dict:
    """A stock template in UI format whose loader declares one model."""
    return {
        "nodes": [
            {
                "id": 1,
                "type": loader,
                "mode": 0,
                "properties": {"models": [{"name": name, "directory": directory, "url": url}]},
                "widgets_values": [name],
            }
        ],
        "links": [],
    }


def stock_templates() -> dict:
    return {
        "unrelated": template_declaring(
            "other.safetensors", "checkpoints", "https://huggingface.co/o/r/resolve/main/x"
        ),
        "wrong_folder": template_declaring(TURBO, "loras", "https://huggingface.co/o/wrong/resolve/main/x"),
        "sdxlturbo_example": template_declaring(TURBO, "checkpoints", TURBO_URL),
    }


def bare_models() -> dict:
    """An API graph naming two checkpoints it gives no source for: one a stock template declares, one nothing does."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": TURBO}},
        "2": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "add-detail-xl.safetensors"}},
    }


async def test_a_bare_missing_model_takes_its_source_from_a_stock_template():
    got = (await validate(bare_models(), Fake(templates=stock_templates())))["requirements"]
    turbo, nothing = got["missing_models"]
    assert turbo["source"] == {
        "declared_by": "template",
        "template": "sdxlturbo_example",
        "directory": "checkpoints",
        "url": TURBO_URL,
    }
    assert turbo["directory"] == "checkpoints" and "url" not in turbo  # url stays the workflow's own declaration
    assert nothing["source"] is None
    [entry] = got["proposals"]["comfy_yaml_models"]
    assert entry["files"] == [{"source": "hf:stabilityai/sdxl-turbo", "file": TURBO, "install": "models/checkpoints/"}]
    [note] = [n for n in got["notes"] if "source null" in n]
    assert note.startswith("1 missing model(s) have no source") and "no stock template on this instance" in note


async def test_a_template_in_another_folder_is_a_source_but_not_a_proposal():
    """The loader's options are checkpoints'; a template declares that file name under loras. It is the source,
    with its folder, but nothing is proposed: that folder doesn't suit this loader."""
    templates = {"wrong_folder": stock_templates()["wrong_folder"]}
    got = (await validate(bare_models(), Fake(templates=templates)))["requirements"]
    turbo, nothing = got["missing_models"]
    assert (turbo["source"]["template"], turbo["source"]["directory"], turbo["directory"]) == (
        "wrong_folder",
        "loras",
        "checkpoints",
    )
    assert nothing["source"] is None and "proposals" not in got


async def test_the_template_index_is_built_once_per_templates_version():
    fake = Fake(templates=stock_templates())
    server, _ = build_server(settings(), comfyui=fake.client())
    async with Client(server, mode="legacy") as client:
        for _ in range(2):
            got = (await client.call_tool("workflow_validate", {"workflow": bare_models()})).structured_content
            assert got["requirements"]["missing_models"][0]["source"]["template"] == "sdxlturbo_example"
    assert fake.calls.count("/templates/index.json") == 1
    assert fake.calls.count("/templates/sdxlturbo_example.json") == 1


async def test_templates_that_cant_be_read_say_so_instead_of_implying_none_declare_it(monkeypatch):
    got = (await validate(bare_models(), Fake()))["requirements"]  # this fake serves no templates at all
    assert [m["source"] for m in got["missing_models"]] == [None, None]
    assert any(
        "2 missing model(s) have no source" in n and "weren't checked (comfyui_http_error)" in n for n in got["notes"]
    )
    monkeypatch.setattr(req, "TEMPLATE_SOURCES_SECONDS", 0.2)
    fake = Fake(templates=stock_templates())
    fake.delays["/templates/index.json"] = 2
    got = (await validate(bare_models(), fake))["requirements"]
    assert any("weren't checked (timeout)" in n for n in got["notes"])
    assert got["satisfied"] is False


async def test_a_template_read_in_part_says_how_far():
    fake = Fake(templates=stock_templates())
    fake.fail["/templates/unrelated.json"] = 500
    got = (await validate(bare_models(), fake))["requirements"]
    assert got["missing_models"][0]["source"]["template"] == "sdxlturbo_example"
    assert any("were checked in part (2 of 3 read in time)" in n for n in got["notes"])


async def test_a_workflow_declared_source_wins_and_says_so():
    graph = {"nodes": [template_declaring("mine.safetensors", "checkpoints", "https://example.com/mine")["nodes"][0]]}
    graph["links"] = []
    got = (await validate(graph, Fake(templates=stock_templates())))["requirements"]
    [model] = got["missing_models"]
    assert model["source"] == {"declared_by": "workflow", "url": "https://example.com/mine"}
    assert not any("source null" in n for n in got["notes"])


# -- a UI node's model, judged by the widget value it uses --------------------------------


def lora_node(widget: str) -> dict:
    return {
        "nodes": [
            {
                "id": 1,
                "type": "LoraLoader",
                "mode": 0,
                "properties": {"models": [{"name": "detail.safetensors", "directory": "loras"}]},
                "widgets_values": [widget, 1.0, 1.0],
            }
        ],
        "links": [],
    }


async def test_a_ui_model_fixed_in_its_widget_is_no_longer_flagged():
    """properties.models declares the bare name; once the widget names the file's real path, nothing is wrong."""
    converted = {"1": {"class_type": "LoraLoader", "inputs": {"lora_name": "style/detail.safetensors"}}}
    fixed = (await validate(lora_node("style/detail.safetensors"), converter=FakeConverter(converted)))["requirements"]
    assert fixed["models_need_value_change"] == [] and fixed["missing_models"] == [] and fixed["satisfied"] is True
    unfixed = (await validate(lora_node("detail.safetensors")))["requirements"]
    [moved] = unfixed["models_need_value_change"]
    assert (moved["name"], moved["found_at"]) == ("detail.safetensors", "style/detail.safetensors")


async def test_a_ui_model_is_reported_under_the_name_its_widget_uses():
    got = (await validate(lora_node("other/detail.safetensors")))["requirements"]
    [model] = got["missing_models"]
    assert (model["name"], model["directory"]) == ("other/detail.safetensors", "loras")


# -- #231: a converted UI graph's missing classes keep their names --------------------------


SUBGRAPH = "5b1f6c2e-8d4a-4c2e-9f61-3a7e0c9d2b10"


def ui_with_uninstalled_classes() -> dict:
    return {
        "nodes": [
            {"id": 8, "type": "ConstrainImage|pysssss", "mode": 0, "properties": {"cnr_id": "comfyui-custom-scripts"}},
            {"id": 10, "type": SUBGRAPH, "mode": 0},
            {"id": 11, "type": "SaveImage", "mode": 0},
        ],
        "links": [],
        "definitions": {
            "subgraphs": [
                {
                    "id": SUBGRAPH,
                    "nodes": [{"id": 20, "type": "GetImageSizeAndCount", "mode": 0, "properties": {"aux_id": "a/b"}}],
                }
            ]
        },
    }


async def test_a_converted_ui_graphs_missing_classes_are_named_in_errors_and_requirements():
    """The frontend converts an uninstalled class with no class_type; the UI graph names it, subgraphs included."""
    converted = {
        "8": {"class_type": None, "inputs": {}},
        "10:20": {"class_type": None, "inputs": {}},
        "11": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "x"}},
    }
    info = {**INFO, "GetImageSize": node_spec(("INT", "INT"))}
    got = await validate(ui_with_uninstalled_classes(), Fake(info), FakeConverter(converted))
    named = {e["node_id"]: e for e in got["errors"] if e["type"] == "missing_node_type"}
    assert named["8"]["class_type"] == "ConstrainImage|pysssss"
    assert named["10:20"]["class_type"] == "GetImageSizeAndCount"
    assert named["10:20"]["expected"] == ["GetImageSize"]
    assert "the UI graph's node 10:20 is a 'GetImageSizeAndCount'" in named["10:20"]["details"]
    assert named["8"]["message"].startswith("Node 'ID #8' has no class_type")  # ComfyUI's wording, as before
    classes = {n["class_type"] for n in got["requirements"]["missing_nodes"]}
    assert classes == {"ConstrainImage|pysssss", "GetImageSizeAndCount"}


# -- the second review of c7c4119 ----------------------------------------------------------


async def test_an_undeclared_node_using_the_bare_name_is_still_checked():
    """R-A: node 20 declares juggernaut and its widget uses the subfolder path that exists; node 999 declares
    nothing and uses the bare name, which ComfyUI refuses. The second must still be reported."""
    jugg = "juggernaut.safetensors"
    info = {
        **INFO,
        "CheckpointLoaderSimple": node_spec(("MODEL",), input={"required": {"ckpt_name": combo(f"sdxl/{jugg}")}}),
    }
    fake = Fake(info, {**FOLDERS, "checkpoints": [f"sdxl/{jugg}"]})
    ui = {
        "nodes": [
            {
                "id": 20,
                "type": "CheckpointLoaderSimple",
                "mode": 0,
                "properties": {"models": [{"name": jugg, "directory": "checkpoints", "url": "https://h/x"}]},
                "widgets_values": [f"sdxl/{jugg}"],
            },
            {"id": 999, "type": "CheckpointLoaderSimple", "mode": 0, "widgets_values": [jugg]},
        ],
        "links": [],
    }
    converted = {
        "20": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": f"sdxl/{jugg}"}},
        "999": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": jugg}},
    }
    got = (await validate(ui, fake, FakeConverter(converted)))["requirements"]
    [moved] = got["models_need_value_change"]
    assert (moved["name"], moved["node_id"], moved["found_at"]) == (jugg, "999", f"sdxl/{jugg}")
    assert got["satisfied"] is False


def templates_for(name: str, *declared: tuple[str, str, str]) -> dict:
    """Stock templates declaring `name`: (template, folder, declaring loader) each."""
    return {
        t: template_declaring(name, folder, f"https://huggingface.co/o/{t}/resolve/main/{name}", loader)
        for t, folder, loader in declared
    }


def loader_graph(loader: str, name: str) -> tuple[dict, dict]:
    """An API graph whose `loader` names `name`, and /object_info where that loader lists no files, so no folder can
    be told from its options."""
    info = {**INFO, loader: node_spec(("MODEL",), input={"required": {"model_name": combo()}})}
    return {"1": {"class_type": loader, "inputs": {"model_name": name}}}, info


async def test_a_template_for_another_loader_gives_a_source_but_no_folder_or_proposal():
    """R-B: UNETLoader reads diffusion_models; a template's CheckpointLoaderSimple puts the file in checkpoints."""
    graph, info = loader_graph("UNETLoader", TURBO)
    templates = templates_for(TURBO, ("sdxlturbo_example", "checkpoints", "CheckpointLoaderSimple"))
    got = (await validate(graph, Fake(info, templates=templates)))["requirements"]
    [model] = got["missing_models"]
    assert model["source"]["template"] == "sdxlturbo_example" and model["source"]["directory"] == "checkpoints"
    assert "directory" not in model  # never taken from a template
    assert "proposals" not in got
    assert any("may not suit this graph's loader" in n for n in got["notes"])


async def test_templates_of_the_same_loader_that_disagree_on_the_folder_give_no_proposal():
    graph, info = loader_graph("FluxLoader", "flux1-dev-fp8.safetensors")
    templates = templates_for(
        "flux1-dev-fp8.safetensors",
        ("flux_a", "checkpoints", "FluxLoader"),
        ("flux_b", "diffusion_models", "FluxLoader"),
    )
    got = (await validate(graph, Fake(info, templates=templates)))["requirements"]
    [model] = got["missing_models"]
    assert model["source"]["template"] == "flux_a" and "directory" not in model
    assert "proposals" not in got


async def test_templates_of_the_same_loader_that_agree_give_a_proposal_in_their_folder():
    graph, info = loader_graph("FluxLoader", "flux1-dev-fp8.safetensors")
    templates = templates_for(
        "flux1-dev-fp8.safetensors",
        ("other_loader", "checkpoints", "CheckpointLoaderSimple"),
        ("flux_a", "diffusion_models", "FluxLoader"),
        ("flux_b", "diffusion_models", "FluxLoader"),
    )
    got = (await validate(graph, Fake(info, templates=templates)))["requirements"]
    [model] = got["missing_models"]
    assert model["source"]["template"] == "flux_a" and "directory" not in model
    [entry] = got["proposals"]["comfy_yaml_models"]
    assert entry["files"][0]["install"] == "models/diffusion_models/"


async def test_in_a_known_folder_the_template_of_the_graphs_loader_is_preferred():
    templates = templates_for(
        TURBO,
        ("first", "checkpoints", "SomeOtherLoader"),
        ("second", "checkpoints", "CheckpointLoaderSimple"),
    )
    graph = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": TURBO}}}
    got = (await validate(graph, Fake(templates=templates)))["requirements"]
    assert got["missing_models"][0]["source"]["template"] == "second"


async def test_a_declaration_no_widget_uses_is_skipped_with_a_note():
    """The node declares the turbo checkpoint, but its widget loads a file that is there: that's what runs."""
    ui = {
        "nodes": [
            {
                "id": 1,
                "type": "CheckpointLoaderSimple",
                "mode": 0,
                "properties": {"models": [{"name": TURBO, "directory": "checkpoints", "url": TURBO_URL}]},
                "widgets_values": [f"sd15/{SD15}"],
            }
        ],
        "links": [],
    }
    converted = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": f"sd15/{SD15}"}}}
    got = (await validate(ui, converter=FakeConverter(converted)))["requirements"]
    assert got["missing_models"] == [] and got["satisfied"] is True
    assert got["notes"] == [req._stale_note(1)]


async def test_a_windows_path_is_matched_with_forward_slashes():
    windows = f"sd15\\{SD15}"
    api = await validate({"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": windows}}})
    [moved] = api["requirements"]["models_need_value_change"]
    assert (moved["name"], moved["found_at"]) == (windows, f"sd15/{SD15}")
    ui = {
        "nodes": [
            {
                "id": 1,
                "type": "CheckpointLoaderSimple",
                "mode": 0,
                "properties": {"models": [{"name": SD15, "directory": "checkpoints"}]},
                "widgets_values": [windows],
            },
            {
                "id": 2,
                "type": "CheckpointLoaderSimple",
                "mode": 0,
                "properties": {
                    "models": [{"name": "sub\\new.safetensors", "directory": "checkpoints", "url": "https://h/n"}]
                },
                "widgets_values": ["sub\\new.safetensors"],
            },
        ],
        "links": [],
    }
    got = (await validate(ui))["requirements"]
    [moved] = got["models_need_value_change"]
    assert (moved["name"], moved["found_at"]) == (windows, f"sd15/{SD15}")
    [entry] = got["proposals"]["comfy_yaml_models"]
    assert entry["files"][0]["as"] == "sub/new.safetensors"  # comfy.yaml takes no backslash


# -- the third review of 4292b62 ----------------------------------------------------------


async def test_a_template_declaring_the_file_in_another_folder_is_a_source_never_none():
    """UNETLoader's folder is known (diffusion_models lists one file); the only template declares the file in
    checkpoints. That template is still the source, with its folder and no proposal: not "none declares it"."""
    info = {**INFO, "UNETLoader": node_spec(("MODEL",), input={"required": {"unet_name": combo("other.safetensors")}})}
    folders = {**FOLDERS, "diffusion_models": ["other.safetensors"]}
    graph = {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": TURBO}}}
    templates = {"sdxlturbo_example": stock_templates()["sdxlturbo_example"]}
    got = (await validate(graph, Fake(info, folders, templates)))["requirements"]
    [model] = got["missing_models"]
    assert model["directory"] == "diffusion_models"  # the loader's, as before
    assert model["source"] == {
        "declared_by": "template",
        "template": "sdxlturbo_example",
        "directory": "checkpoints",
        "url": TURBO_URL,
    }
    assert "proposals" not in got
    assert any("may not suit this graph's loader" in n for n in got["notes"])
    assert not any("source null" in n for n in got["notes"])


async def test_model_declarations_whose_name_or_folder_is_not_a_string_cost_nothing():
    """In the graph or in a stock template, a properties.models entry with a list or an object for its name or
    folder is skipped, as the template check skips it; the report is made all the same."""
    broken = [{"name": ["x"], "directory": "checkpoints"}, {"name": "y.safetensors", "directory": {"a": 1}}]
    template = template_declaring(TURBO, "checkpoints", TURBO_URL)
    template["nodes"][0]["properties"]["models"] = broken + template["nodes"][0]["properties"]["models"]
    ui = {"nodes": [{**template["nodes"][0], "id": 5}], "links": []}
    got = await validate(ui, Fake(templates={"sdxlturbo_example": template}))
    assert got["requirements_unchecked"] is None
    assert [m["name"] for m in got["requirements"]["missing_models"]] == [TURBO]
    api = await validate(bare_models(), Fake(templates={"sdxlturbo_example": template}))
    assert api["requirements"]["missing_models"][0]["source"]["template"] == "sdxlturbo_example"
