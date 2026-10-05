"""The read profile's introspection tools, against a fake ComfyUI: node_search,
node_describe, model_list, template_search and template_get."""

from __future__ import annotations

import asyncio
import json

import httpx2
import pytest
from comfyrelay import tools_introspection
from comfyrelay.comfyui import ComfyUIClient
from comfyrelay.server import build_server
from mcp import Client
from relay_helpers import SYSTEM_STATS, settings

pytestmark = pytest.mark.anyio

LONG_COMBO = [f"model_{i:03}.safetensors" for i in range(120)]

OBJECT_INFO = {
    "CheckpointLoaderSimple": {
        "input": {
            "required": {"ckpt_name": [["sd15.safetensors", "sdxl.safetensors"], {"tooltip": "The checkpoint."}]}
        },
        "input_order": {"required": ["ckpt_name"]},
        "output": ["MODEL", "CLIP", "VAE"],
        "output_is_list": [False, False, False],
        "output_name": ["MODEL", "CLIP", "VAE"],
        "output_tooltips": ["The model.", "The CLIP.", "The VAE."],
        "name": "CheckpointLoaderSimple",
        "display_name": "Load Checkpoint",
        "description": "Loads a diffusion model checkpoint. Diffusion models denoise latents.",
        "python_module": "nodes",
        "category": "model/loaders",
        "output_node": False,
        "search_aliases": ["load model", "ckpt"],
    },
    "CheckpointLoader": {
        "input": {"required": {"config_name": [[]], "ckpt_name": [[]]}},
        "output": ["MODEL", "CLIP", "VAE"],
        "name": "CheckpointLoader",
        "display_name": "Load Checkpoint With Config (DEPRECATED)",
        "description": "",
        "python_module": "nodes",
        "category": "model/loaders",
        "output_node": False,
        "deprecated": True,
    },
    "unCLIPCheckpointLoader": {
        "input": {"required": {"ckpt_name": [[]]}},
        "output": ["MODEL", "CLIP", "VAE", "CLIP_VISION"],
        "display_name": "Load unCLIP Checkpoint",
        "python_module": "nodes",
        "category": "model/loaders",
    },
    "KSampler": {
        "input": {
            "required": {
                "model": ["MODEL", {"tooltip": "The model."}],
                "seed": ["INT", {"default": 0, "min": 0, "max": 18446744073709551615, "control_after_generate": True}],
                "cfg": ["FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01}],
                "sampler_name": [LONG_COMBO],
            },
            "optional": {"denoise": ["FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}]},
            "hidden": {"prompt": "PROMPT", "unique_id": "UNIQUE_ID"},
        },
        "input_order": {"required": ["model", "seed", "cfg", "sampler_name"], "optional": ["denoise"]},
        "output": ["LATENT"],
        "output_is_list": [False],
        "output_name": ["LATENT"],
        "display_name": "KSampler",
        "description": "Uses the provided model to denoise the latent image.",
        "python_module": "nodes",
        "category": "sampling",
        "output_node": False,
    },
    # The shapes of ComfyUI's V3 dynamic inputs (comfy_api/latest/_io.py), from
    # ResizeImageMaskNode and BatchImagesNode at v0.37.0, with a nested combo and
    # a names-form Autogrow added to exercise the dotted naming at depth.
    "ResizeImageMaskNode": {
        "input": {
            "required": {
                "input": [
                    "COMFY_MATCHTYPE_V3",
                    {"template": {"template_id": "input_type", "allowed_types": "IMAGE,MASK"}},
                ],
                "resize_type": [
                    "COMFY_DYNAMICCOMBO_V3",
                    {
                        "tooltip": "How to resize.",
                        "options": [
                            {"key": "by factor", "inputs": {"required": {"factor": ["FLOAT", {"default": 1.0}]}}},
                            {
                                "key": "to size",
                                "inputs": {
                                    "required": {
                                        "width": ["INT", {"default": 512}],
                                        "crop": [
                                            "COMFY_DYNAMICCOMBO_V3",
                                            {
                                                "options": [
                                                    {"key": "none", "inputs": {"required": {}}},
                                                    {"key": "offset", "inputs": {"required": {"x": ["INT", {}]}}},
                                                ]
                                            },
                                        ],
                                    },
                                    "optional": {
                                        "refs": [
                                            "COMFY_AUTOGROW_V3",
                                            {
                                                "template": {
                                                    "input": {"optional": {"ref": ["IMAGE", {}]}},
                                                    "names": ["first", "second"],
                                                    "min": 0,
                                                }
                                            },
                                        ]
                                    },
                                },
                            },
                        ],
                    },
                ],
                "method": ["COMBO", {"default": "area", "options": ["area", "bicubic"], "multiselect": False}],
            }
        },
        "input_order": {"required": ["input", "resize_type", "method"]},
        "output": ["COMFY_MATCHTYPE_V3"],
        "output_name": ["resized"],
        "output_matchtypes": ["input_type"],
        "display_name": "Resize Image/Mask",
        "python_module": "comfy_extras.nodes_images",
        "category": "transform",
        "output_node": False,
    },
    "BatchImagesNode": {
        "input": {
            "required": {
                "images": [
                    "COMFY_AUTOGROW_V3",
                    {
                        "template": {
                            "input": {"required": {"image": ["IMAGE", {}]}},
                            "prefix": "image",
                            "min": 2,
                            "max": 50,
                        }
                    },
                ]
            }
        },
        "output": ["IMAGE"],
        "display_name": "Batch Images",
        "python_module": "comfy_extras.nodes_post_processing",
        "category": "image/batch",
        "output_node": False,
    },
    "LoadImage": {
        "input": {"required": {"image": [["present.png", "sub/other.png"], {"image_upload": True}]}},
        "output": ["IMAGE", "MASK"],
        "display_name": "Load Image",
        "python_module": "nodes",
        "category": "image",
        "output_node": False,
    },
    "MathExpression|pysssss": {
        "input": {"required": {"expression": ["STRING", {"multiline": True, "dynamicPrompts": False}]}},
        "output": ["INT", "FLOAT"],
        "output_name": ["INT", "FLOAT"],
        "display_name": "Math Expression 🐍",
        "description": "Evaluates a math expression.",
        "python_module": "custom_nodes.ComfyUI-Custom-Scripts",
        "category": "utils",
        "output_node": True,
    },
    "OpenAIDalle3": {
        "input": {"required": {"prompt": ["STRING", {"multiline": True}]}},
        "output": ["IMAGE"],
        "display_name": "OpenAI DALL·E 3",
        "description": "Generates an image from a prompt through OpenAI's API.",
        "python_module": "comfy_api_nodes.nodes_openai",
        "category": "api node/image/OpenAI",
        "output_node": False,
        "api_node": True,
    },
    "SaveImage": {
        "input": {"required": {"images": ["IMAGE"], "filename_prefix": ["STRING", {"default": "ComfyUI"}]}},
        "output": [],
        "display_name": "Save Image",
        "description": "Saves the input images to your ComfyUI output directory.",
        "python_module": "nodes",
        "category": "image",
        "output_node": True,
    },
}


def model(name: str, directory: str) -> dict:
    return {"name": name, "url": f"https://example.test/{name}", "directory": directory}


def node(kind: str, *, mode: int = 0, models: list | None = None, cnr: str = "comfy-core") -> dict:
    props = {"cnr_id": cnr, "ver": "1.0.0"}
    if models:
        props["models"] = models
    return {"id": 1, "type": kind, "mode": mode, "properties": props, "widgets_values": []}


SUBGRAPH = "9d1c2e1a-0000-4000-8000-000000000001"
TEMPLATES = {
    # Everything present: a runnable template.
    "sd15_simple": {
        "nodes": [
            node("CheckpointLoaderSimple", models=[model("sd15.safetensors", "checkpoints")]),
            node("KSampler"),
            node("SaveImage"),
            node("MarkdownNote"),
            node("Reroute"),
        ]
    },
    # A missing custom node inside a subgraph, a missing model, a bypassed node
    # whose class and model are both absent (it doesn't run, so neither counts),
    # and a model in a folder this ComfyUI doesn't know.
    "flux_custom": {
        "nodes": [node(SUBGRAPH), node("GhostNode", mode=4, models=[model("ghost.safetensors", "loras")])],
        "definitions": {
            "subgraphs": [
                {
                    "id": SUBGRAPH,
                    "nodes": [
                        node("CheckpointLoaderSimple", models=[model("flux1-dev.safetensors", "checkpoints")]),
                        node("ImageRemoveAlpha+", cnr="comfyui_essentials"),
                        node("ImageRemoveAlpha+", cnr="comfyui_essentials"),
                        node("SAMLoader", models=[model("sam_vit_b.pth", "sams")]),
                    ],
                }
            ]
        },
    },
    # A partner-API template.
    "api_dalle": {"nodes": [node("OpenAIDalle3"), node("SaveImage")]},
    "video_wan": {"nodes": [node("SaveImage")]},
    # Input files: one missing, one present, one fed by a link (so its widget
    # value is not used), and a missing one inside a bypassed node.
    "restore_photo": {
        "nodes": [
            {**node("LoadImage"), "widgets_values": ["old_photo.png", "image"]},
            {**node("LoadImage"), "widgets_values_named": {"image": "present.png"}, "widgets_values": []},
            {**node("LoadImage"), "widgets_values": ["linked.png"], "inputs": [{"name": "image", "link": 7}]},
            {**node("LoadImage", mode=4), "widgets_values": ["bypassed.png"]},
            node("SaveImage"),
        ]
    },
    # The declared checkpoint is on disk only in a subfolder.
    "sdxl_sub": {"nodes": [node("CheckpointLoaderSimple", models=[model("sdxl_base.safetensors", "checkpoints")])]},
    # Uses a partner-API node although the index doesn't flag it.
    "restore_cloud": {"nodes": [node("OpenAIDalle3"), node("SaveImage")]},
}
INDEX = [
    {
        "moduleName": "default",
        "category": "Foundation",
        "title": "Image",
        "templates": [
            {
                "name": "sd15_simple",
                "title": "SD1.5: Text to Image",
                "description": "Generate images from text with SD1.5.",
                "tags": ["Text to Image", "Image"],
                "models": ["SD1.5"],
                "mediaType": "image",
                "openSource": True,
                "usage": 50,
                "username": "ComfyUI",
                "minComfyUIVersion": "0.3.0",
            },
            {
                "name": "flux_custom",
                "title": "Flux Dev: Text to Image with background removal",
                "description": "Generate images from text with Flux, then cut out the background.",
                "tags": ["Text to Image", "Image"],
                "models": ["Flux"],
                "mediaType": "image",
                "openSource": True,
                "usage": 900,
            },
            {
                "name": "api_dalle",
                "title": "OpenAI DALL·E 3: Text to Image",
                "description": "Generate images from text through OpenAI's API.",
                "tags": ["Text to Image", "Image", "API"],
                "models": ["DALL·E"],
                "mediaType": "image",
                "openSource": False,
                "usage": 5000,
            },
        ],
    },
    {
        "moduleName": "default",
        "category": "Foundation",
        "title": "Video",
        "templates": [{"name": "video_wan", "title": "Wan 2.1: Text to Video", "tags": ["Video"], "models": ["Wan"]}],
    },
    {
        "moduleName": "default",
        "category": "Utility",
        "title": "Tools",
        "templates": [
            {"name": "restore_photo", "title": "Restore a photo", "tags": ["Restore"], "usage": 10},
            {"name": "sdxl_sub", "title": "SDXL base from a subfolder", "tags": ["SDXL"]},
            {"name": "restore_cloud", "title": "Restore with a cloud model", "tags": ["Restore"], "usage": 99},
        ],
    },
]
MODEL_FOLDERS = ["checkpoints", "loras", "vae", "custom_nodes", "download_model_base"]
MODEL_FILES = {"checkpoints": ["sd15.safetensors", "sdxl/sdxl_base.safetensors"], "loras": [], "vae": []}
STATS = {"system": {**SYSTEM_STATS["system"], "installed_templates_version": "0.11.66"}, "devices": []}


def routes(**overrides) -> dict[str, httpx2.Response]:
    out = {
        "/system_stats": httpx2.Response(200, json=STATS),
        "/object_info": httpx2.Response(200, json=OBJECT_INFO),
        "/models": httpx2.Response(200, json=MODEL_FOLDERS),
        "/templates/index.json": httpx2.Response(200, json=INDEX),
    }
    for name, info in OBJECT_INFO.items():
        out[f"/object_info/{name.replace('|', '%7C')}"] = httpx2.Response(200, json={name: info})
    for folder, files in MODEL_FILES.items():
        out[f"/models/{folder}"] = httpx2.Response(200, json=files)
    for name, workflow in TEMPLATES.items():
        out[f"/templates/{name}.json"] = httpx2.Response(200, json=workflow)
    out.update(overrides)
    return out


async def call(tool: str, args: dict, **overrides):
    """Call `tool`; unknown /object_info/<class> answers {} as ComfyUI does. An override may be an async function
    that answers, or raises, in place of a response."""
    table = routes(**overrides)

    async def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.raw_path.decode()
        if path in table:
            return await table[path]() if callable(table[path]) else table[path]
        if path.startswith("/object_info/"):
            return httpx2.Response(200, json={})
        return httpx2.Response(404)

    client = ComfyUIClient("http://comfyui.test:8188", transport=httpx2.MockTransport(handler))
    server, _ = build_server(settings(profiles=("read",)), comfyui=client)
    async with Client(server, mode="legacy") as mcp:
        return await mcp.call_tool(tool, args)


async def ok(tool: str, args: dict, **overrides) -> dict:
    result = await call(tool, args, **overrides)
    assert not result.is_error, result.content[0].text
    return result.structured_content


async def error(tool: str, args: dict, **overrides) -> dict:
    result = await call(tool, args, **overrides)
    assert result.is_error
    text = result.content[0].text
    return json.loads(text[text.index("{") :])["error"]


# -- node_search ----------------------------------------------------------------


async def test_search_ranks_the_exact_name_before_its_near_namesakes():
    got = await ok("node_search", {"query": "CheckpointLoader"})
    assert [(h["class_type"], h["match"]) for h in got["results"]] == [
        ("CheckpointLoader", "exact"),
        ("CheckpointLoaderSimple", "prefix"),
        ("unCLIPCheckpointLoader", "name"),
    ]
    assert got["results"][0]["deprecated"] is True
    assert got["node_count"] == len(OBJECT_INFO)


async def test_search_matches_a_display_name_exactly_and_ignores_spacing_and_case():
    got = await ok("node_search", {"query": "load checkpoint"})
    assert got["results"][0] == {
        "class_type": "CheckpointLoaderSimple",
        "display_name": "Load Checkpoint",
        "category": "model/loaders",
        "summary": "Loads a diffusion model checkpoint.",
        "match": "exact",
    }
    assert (await ok("node_search", {"query": "checkpointloadersimple"}))["results"][0]["match"] == "exact"


async def test_search_reaches_aliases_categories_and_descriptions():
    assert (await ok("node_search", {"query": "ckpt"}))["results"][0]["class_type"] == "CheckpointLoaderSimple"
    by_category = await ok("node_search", {"query": "sampling"})
    assert [(h["class_type"], h["match"]) for h in by_category["results"]] == [("KSampler", "category")]
    by_description = await ok("node_search", {"query": "output directory"})
    assert [(h["class_type"], h["match"]) for h in by_description["results"]] == [("SaveImage", "description")]


async def test_search_includes_custom_nodes_and_flags_partner_api_nodes():
    custom = (await ok("node_search", {"query": "math expression"}))["results"][0]
    assert custom["class_type"] == "MathExpression|pysssss"
    assert custom["pack"] == "ComfyUI-Custom-Scripts"
    api = (await ok("node_search", {"query": "dall"}))["results"][0]
    assert (api["class_type"], api["api_node"]) == ("OpenAIDalle3", True)


async def test_search_ranks_partner_api_nodes_after_the_rest_of_their_tier():
    got = await ok("node_search", {"query": "image"})
    names = [h["class_type"] for h in got["results"]]
    assert names.index("OpenAIDalle3") > names.index("SaveImage")


async def test_search_limit_and_no_match():
    got = await ok("node_search", {"query": "checkpoint", "limit": 1})
    assert (got["total_matches"], len(got["results"])) == (3, 1)
    assert (await ok("node_search", {"query": "no such thing"}))["results"] == []


# -- node_describe ----------------------------------------------------------------


async def test_describe_a_built_in():
    got = await ok("node_describe", {"class_type": "KSampler"})
    assert got["class_type"] == "KSampler"
    assert (got["output_node"], got["api_node"], got.get("pack")) == (False, False, None)
    inputs = {i["name"]: i for i in got["inputs"]}
    assert [i["name"] for i in got["inputs"]] == ["model", "seed", "cfg", "sampler_name", "denoise"]
    assert inputs["model"] == {"name": "model", "type": "MODEL", "required": True, "tooltip": "The model."}
    assert inputs["cfg"] == {
        "name": "cfg",
        "type": "FLOAT",
        "required": True,
        "default": 8.0,
        "min": 0.0,
        "max": 100.0,
        "step": 0.1,
        "other": {"round": 0.01},
    }
    assert inputs["seed"]["max"] == 18446744073709551615
    assert inputs["denoise"]["required"] is False
    assert got["hidden_inputs"] == ["prompt", "unique_id"]
    assert got["outputs"] == [{"index": 0, "type": "LATENT", "name": "LATENT", "is_list": False}]


async def test_describe_truncates_a_long_combo_and_counts_it():
    sampler = next(
        i for i in (await ok("node_describe", {"class_type": "KSampler"}))["inputs"] if i["name"] == "sampler_name"
    )
    assert sampler["type"] == "COMBO"
    assert sampler["options"] == LONG_COMBO[:20]
    assert (sampler["options_total"], sampler["options_truncated"]) == (120, True)
    wide = await ok("node_describe", {"class_type": "KSampler", "max_options": 500})
    sampler = next(i for i in wide["inputs"] if i["name"] == "sampler_name")
    assert sampler["options"] == LONG_COMBO and "options_truncated" not in sampler


async def test_describe_dynamic_combo_inputs_are_named_with_their_combo_path():
    """ComfyUI names a DynamicCombo's inputs <combo>.<input> (finalize_prefix), at every depth."""
    got = await ok("node_describe", {"class_type": "ResizeImageMaskNode"})
    _, resize, method = got["inputs"]
    assert (method["type"], method["options"], method["default"]) == ("COMBO", ["area", "bicubic"], "area")
    assert method["other"] == {"multiselect": False}
    assert resize["type"] == "COMFY_DYNAMICCOMBO_V3"
    assert "other" not in resize  # the options are rendered, not dumped raw
    by_factor, to_size = resize["options"]
    assert by_factor == {
        "value": "by factor",
        "inputs": [{"name": "resize_type.factor", "type": "FLOAT", "required": True, "default": 1.0}],
    }
    assert to_size["value"] == "to size"
    width, crop, refs = to_size["inputs"]
    assert width["name"] == "resize_type.width"
    assert crop["name"] == "resize_type.crop"
    assert crop["options"][1] == {
        "value": "offset",
        "inputs": [{"name": "resize_type.crop.x", "type": "INT", "required": True}],
    }
    assert refs["name"] == "resize_type.refs" and refs["required"] is False
    assert refs["autogrow"]["names"] == ["resize_type.refs.first", "resize_type.refs.second"]
    assert "prefix" not in refs["autogrow"]


async def test_describe_autogrow_as_a_naming_rule():
    (images,) = (await ok("node_describe", {"class_type": "BatchImagesNode"}))["inputs"]
    assert images["type"] == "COMFY_AUTOGROW_V3"
    assert "other" not in images  # no raw template
    grow = images["autogrow"]
    assert grow["prefix"] == "images.image"
    assert (grow["min"], grow["max"], grow["names_total"], grow["names_truncated"]) == (2, 50, 50, True)
    assert grow["names"][:3] == ["images.image0", "images.image1", "images.image2"]
    assert len(grow["names"]) == 20
    assert grow["item"] == {"name": "images.image<n>", "type": "IMAGE", "required": True}


async def test_describe_match_type_input_and_output():
    got = await ok("node_describe", {"class_type": "ResizeImageMaskNode"})
    matched = got["inputs"][0]
    assert matched["name"] == "input"
    assert matched["match_type"] == {"template_id": "input_type", "allowed_types": ["IMAGE", "MASK"]}
    assert "other" not in matched
    assert got["outputs"] == [
        {"index": 0, "type": "COMFY_MATCHTYPE_V3", "name": "resized", "is_list": False, "same_type_as": "input"}
    ]


async def test_describe_dynamic_slot():
    slot = {
        "input": {
            "optional": {
                "latent": [
                    "COMFY_DYNAMICSLOT_V3",
                    {"slotType": "LATENT", "inputs": {"required": {"strength": ["FLOAT", {}]}}},
                ]
            }
        },
        "output": [],
    }
    got = await ok(
        "node_describe",
        {"class_type": "SlotNode"},
        **{"/object_info/SlotNode": httpx2.Response(200, json={"SlotNode": slot})},
    )
    assert got["inputs"] == [
        {
            "name": "latent",
            "type": "LATENT",
            "required": False,
            "slot_inputs": [{"name": "latent.strength", "type": "FLOAT", "required": True}],
        }
    ]


@pytest.mark.parametrize("class_type", [".", ".."])
async def test_describe_never_sends_a_dot_segment(class_type):
    seen = []
    table = routes()

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.raw_path.decode())
        return table.get(request.url.raw_path.decode(), httpx2.Response(404))

    client = ComfyUIClient("http://comfyui.test:8188", transport=httpx2.MockTransport(handler))
    server, _ = build_server(settings(profiles=("read",)), comfyui=client)
    async with Client(server, mode="legacy") as mcp:
        result = await mcp.call_tool("node_describe", {"class_type": class_type})
    assert result.is_error and "unknown_node_class" in result.content[0].text
    assert seen == ["/object_info"]


async def test_describe_a_custom_node():
    got = await ok("node_describe", {"class_type": "MathExpression|pysssss"})
    assert (got["pack"], got["output_node"]) == ("ComfyUI-Custom-Scripts", True)
    assert got["inputs"][0]["other"] == {"multiline": True, "dynamicPrompts": False}
    assert [o["type"] for o in got["outputs"]] == ["INT", "FLOAT"]


async def test_describe_returns_the_help_page_comfyui_serves():
    help_md = httpx2.Response(200, text="# KSampler\n\nDenoises.", headers={"content-type": "text/markdown"})
    got = await ok("node_describe", {"class_type": "KSampler"}, **{"/docs/KSampler/en.md": help_md})
    assert (got["help"], got["help_path"]) == ("# KSampler\n\nDenoises.", "/docs/KSampler/en.md")


@pytest.mark.parametrize(
    "answer",
    [
        httpx2.Response(404, text="404: Not Found"),
        httpx2.Response(200, html="<!doctype html><title>ComfyUI</title>"),
        httpx2.Response(500, text="500: Internal Server Error"),
    ],
    ids=["404", "an-html-page", "a-500"],
)
async def test_describe_leaves_help_out_when_comfyui_has_none_or_fails_to_serve_it(answer):
    got = await ok("node_describe", {"class_type": "KSampler"}, **{"/docs/KSampler/en.md": answer})
    assert "help" not in got and "help_path" not in got
    assert got["class_type"] == "KSampler"


async def test_a_help_page_past_the_cap_is_cut_and_says_so():
    long = httpx2.Response(200, content=b"x" * (tools_introspection.HELP_MAX_BYTES + 5000))
    got = await ok("node_describe", {"class_type": "KSampler"}, **{"/docs/KSampler/en.md": long})
    assert (len(got["help"]), got["help_truncated"]) == (tools_introspection.HELP_MAX_BYTES, True)


async def test_a_custom_nodes_help_comes_from_its_pack_per_locale_then_without():
    """The editor's order (ComfyUI frontend 1.52): /extensions/<pack>/docs/<class>/<locale>.md, then <class>.md."""
    base = "/extensions/ComfyUI-Custom-Scripts/docs/MathExpression%7Cpysssss"
    got = await ok(
        "node_describe",
        {"class_type": "MathExpression|pysssss"},
        **{f"{base}.md": httpx2.Response(200, text="Evaluates.")},
    )
    assert (got["help"], got["help_path"]) == ("Evaluates.", f"{base}.md")
    got = await ok(
        "node_describe",
        {"class_type": "MathExpression|pysssss"},
        **{f"{base}/en.md": httpx2.Response(200, text="Per locale."), f"{base}.md": httpx2.Response(200, text="x")},
    )
    assert (got["help"], got["help_path"]) == ("Per locale.", f"{base}/en.md")


async def test_describe_an_api_node():
    assert (await ok("node_describe", {"class_type": "OpenAIDalle3"}))["api_node"] is True


async def test_an_unknown_class_suggests_close_matches():
    err = await error("node_describe", {"class_type": "checkpointloadersimple"})
    assert err["code"] == "unknown_node_class"
    assert err["retryable"] is False
    assert err["suggestions"][0] == {"class_type": "CheckpointLoaderSimple", "display_name": "Load Checkpoint"}
    err = await error("node_describe", {"class_type": "Load Checkpoint"})
    assert "CheckpointLoaderSimple" in [s["class_type"] for s in err["suggestions"]]
    assert (await error("node_describe", {"class_type": "Zzzzzz"}))["suggestions"] == []


# -- model_list -------------------------------------------------------------------


async def test_model_list_by_folder_skipping_what_is_not_a_model_folder():
    got = await ok("model_list", {})
    assert got == {
        "folders": [
            {
                "folder": "checkpoints",
                "count": 2,
                "files": ["sd15.safetensors", "sdxl/sdxl_base.safetensors"],
                "truncated": False,
            }
        ],
        "empty_folders": ["loras", "vae"],
    }


async def test_model_list_one_folder_truncated():
    got = await ok("model_list", {"folder": "checkpoints", "max_files": 1})
    assert got["folders"] == [{"folder": "checkpoints", "count": 2, "files": ["sd15.safetensors"], "truncated": True}]
    assert (await ok("model_list", {"folder": "loras"}))["folders"] == [
        {"folder": "loras", "count": 0, "files": [], "truncated": False}
    ]


async def test_model_list_defaults_to_50_per_folder_and_a_total_budget(monkeypatch):
    many = [f"m{i:03}.safetensors" for i in range(70)]
    overrides = {"/models/checkpoints": httpx2.Response(200, json=many), "/models/vae": httpx2.Response(200, json=many)}
    got = await ok("model_list", {}, **overrides)
    assert [(f["folder"], f["count"], len(f["files"]), f["truncated"]) for f in got["folders"]] == [
        ("checkpoints", 70, 50, True),
        ("vae", 70, 50, True),
    ]
    monkeypatch.setattr(tools_introspection, "MAX_TOTAL_FILES", 60)
    got = await ok("model_list", {}, **overrides)
    assert [(f["folder"], len(f["files"]), f["truncated"]) for f in got["folders"]] == [
        ("checkpoints", 50, True),
        ("vae", 10, True),
    ]


@pytest.mark.parametrize("folder", ["sams", "custom_nodes", "download_model_base", ".."])
async def test_model_list_an_unknown_folder(folder):
    err = await error("model_list", {"folder": folder})
    assert err["code"] == "unknown_model_folder"
    assert err["folders"] == ["checkpoints", "loras", "vae"]


# -- template_search / template_get -----------------------------------------------


async def test_template_search_ranks_and_checks_runnability():
    got = await ok("template_search", {"query": "SD1.5 text to image"})
    assert got["source"]["license"] == "MIT"
    assert got["source"]["version"] == "0.11.66"
    # Every word matched first; "sd1.5" is rarer than "image", so it counts for more. A partial match comes last.
    assert [h["name"] for h in got["results"]] == ["sd15_simple", "flux_custom", "video_wan"]
    counts = ("total_matches", "hidden_partner_api", "hidden_not_runnable", "unchecked")
    assert [got[k] for k in counts] == [3, 1, 0, 0]
    runnable = got["results"][0]
    # A hit's summary leaves out every kind with nothing missing.
    assert runnable["runnability"] == {"runnable": True}
    assert got["results"][1]["runnability"] == {
        "runnable": False,
        "missing_nodes": {"count": 2, "first": ["ImageRemoveAlpha+", "SAMLoader"]},
        "missing_models": {"count": 2, "first": ["flux1-dev.safetensors", "sam_vit_b.pth"]},
    }
    assert runnable["category"] == "Foundation / Image"
    assert runnable["model_families"] == ["SD1.5"]
    full = await ok("template_get", {"name": "sd15_simple", "include_workflow": False})
    assert full["runnability"] == {
        "runnable": True,
        "missing_nodes": [],
        "missing_models": [],
        "models_need_value_change": [],
        "missing_inputs": [],
        "api_nodes": [],
        "node_classes_checked": 3,
        "models_checked": 1,
    }


async def test_template_runnability_reports_missing_nodes_and_models():
    check = (await ok("template_get", {"name": "flux_custom", "include_workflow": False}))["runnability"]
    assert check["runnable"] is False
    assert check["missing_nodes"] == [
        {"class_type": "ImageRemoveAlpha+", "pack": "comfyui_essentials", "count": 2},
        {"class_type": "SAMLoader", "pack": "comfy-core", "count": 1},
    ]
    assert check["missing_models"] == [
        {
            "name": "flux1-dev.safetensors",
            "directory": "checkpoints",
            "url": "https://example.test/flux1-dev.safetensors",
            "folder_known": True,
        },
        {
            "name": "sam_vit_b.pth",
            "directory": "sams",
            "url": "https://example.test/sam_vit_b.pth",
            "folder_known": False,
        },
    ]
    # The bypassed GhostNode and its lora are not required.
    assert (check["node_classes_checked"], check["models_checked"]) == (3, 2)


async def test_template_search_partner_api_on_request():
    got = await ok("template_search", {"query": "text to image", "include_partner_api": True})
    assert got["hidden_partner_api"] == 0
    api = next(h for h in got["results"] if h["name"] == "api_dalle")
    assert api["partner_api"] is True
    assert api["runnability"]["runnable"] is False
    assert api["runnability"]["api_nodes"] == {"count": 1, "first": ["OpenAIDalle3"]}


async def test_template_runnability_reports_input_files_the_input_directory_lacks():
    check = (await ok("template_get", {"name": "restore_photo", "include_workflow": False}))["runnability"]
    # present.png is there; linked.png comes over a link; bypassed.png is in a node that doesn't run.
    assert check["missing_inputs"] == [{"class_type": "LoadImage", "input": "image", "file": "old_photo.png"}]
    assert check["runnable"] is False
    assert check["missing_nodes"] == check["missing_models"] == check["api_nodes"] == []


async def test_template_runnability_a_model_only_in_a_subfolder_needs_a_value_change():
    check = (await ok("template_get", {"name": "sdxl_sub", "include_workflow": False}))["runnability"]
    assert check["runnable"] is False
    assert check["missing_models"] == []
    assert check["models_need_value_change"] == [
        {
            "name": "sdxl_base.safetensors",
            "directory": "checkpoints",
            "found_at": "sdxl/sdxl_base.safetensors",
            "needs_value_change": "set the loader's value from 'sdxl_base.safetensors' to 'sdxl/sdxl_base.safetensors'",
        }
    ]


async def test_template_search_drops_hits_whose_graph_uses_partner_api_nodes():
    """restore_cloud isn't flagged in the index, but its graph has an API node."""
    got = await ok("template_search", {"query": "restore"})
    assert [h["name"] for h in got["results"]] == ["restore_photo"]
    assert (got["hidden_partner_api"], got["total_matches"]) == (1, 1)
    shown = await ok("template_search", {"query": "restore", "include_partner_api": True})
    assert [h["name"] for h in shown["results"]] == ["restore_cloud", "restore_photo"]


async def test_a_partner_api_template_stays_hidden_when_a_model_folder_it_names_fails():
    """The graph's API node is known from the template and /object_info alone, so a folder that can't be listed
    doesn't turn a hidden template into a shown, unchecked one."""
    cloud = {"nodes": [node("OpenAIDalle3", models=[model("sd15.safetensors", "checkpoints")]), node("SaveImage")]}
    overrides = {
        "/templates/restore_cloud.json": httpx2.Response(200, json=cloud),
        "/models/checkpoints": httpx2.Response(500),
    }
    got = await ok("template_search", {"query": "restore"}, **overrides)
    assert [h["name"] for h in got["results"]] == ["restore_photo"]
    assert (got["hidden_partner_api"], got["unchecked"]) == (1, 0)
    shown = await ok("template_search", {"query": "restore", "include_partner_api": True}, **overrides)
    cloud_hit = next(h for h in shown["results"] if h["name"] == "restore_cloud")
    assert cloud_hit["runnability"] == {"runnable": None, "unchecked": "comfyui_http_error"}


async def test_template_search_runnable_only_keeps_only_runnable_templates():
    everything = await ok("template_search", {"query": "text"})
    assert [h["name"] for h in everything["results"]] == ["sd15_simple", "video_wan", "flux_custom"]
    got = await ok("template_search", {"query": "text", "runnable_only": True})
    assert [h["name"] for h in got["results"]] == ["sd15_simple", "video_wan"]
    assert {h["runnability"]["runnable"] for h in got["results"]} == {True}
    assert (got["total_matches"], got["hidden_not_runnable"], got["hidden_partner_api"]) == (2, 1, 1)


async def test_template_search_runnable_breaks_ties_between_equal_word_matches_only():
    # "image" matches both titles alike, so flux_custom (usage 900) would lead on usage; sd15_simple runs here.
    got = await ok("template_search", {"query": "image"})
    assert [h["name"] for h in got["results"]] == ["sd15_simple", "flux_custom"]
    # Matching more of the query still outranks being runnable.
    more = await ok("template_search", {"query": "flux image"})
    assert [h["name"] for h in more["results"]] == ["flux_custom", "sd15_simple"]


async def test_template_search_caps_a_hits_runnability_summary():
    many = {
        "nodes": [node(f"Missing{i}" + "x" * 200) for i in range(5)]
        + [node("CheckpointLoaderSimple", models=[model(f"m{i}" + "y" * 200, "checkpoints") for i in range(5)])]
        + [{**node("LoadImage"), "widgets_values": [f"in{i}.png"]} for i in range(5)]
    }
    overrides = {"/templates/flux_custom.json": httpx2.Response(200, json=many)}
    (hit,) = (await ok("template_search", {"query": "flux"}, **overrides))["results"]
    summary = hit["runnability"]
    assert summary["runnable"] is False
    for kind in ("missing_nodes", "missing_models", "missing_inputs"):
        assert summary[kind]["count"] == 5
        assert len(summary[kind]["first"]) == 3
        assert all(len(name) <= 80 for name in summary[kind]["first"])
    assert len(summary["missing_nodes"]["first"][0]) == 80
    # template_get still lists them all, uncut.
    full = (await ok("template_get", {"name": "flux_custom", "include_workflow": False}, **overrides))["runnability"]
    assert len(full["missing_nodes"]) == len(full["missing_models"]) == len(full["missing_inputs"]) == 5


class Counting:
    """One relay over a fake ComfyUI whose answers a test can change between calls, counting template fetches."""

    def __init__(self, **overrides):
        self.table = routes(**overrides)
        self.fetched: list[str] = []
        self.stats = json.loads(json.dumps(STATS))

    async def handler(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.raw_path.decode()
        if path.startswith("/templates/") and path != "/templates/index.json":
            self.fetched.append(path)
        if path == "/system_stats":
            return httpx2.Response(200, json=self.stats)
        answer = self.table.get(path, httpx2.Response(404))
        return await answer() if callable(answer) else answer

    def server(self):
        client = ComfyUIClient("http://comfyui.test:8188", transport=httpx2.MockTransport(self.handler))
        return build_server(settings(profiles=("read",)), comfyui=client)


async def search(mcp, args: dict) -> dict:
    result = await mcp.call_tool("template_search", args)
    assert not result.is_error, result.content[0].text
    return result.structured_content


async def test_template_requirements_are_cached_per_templates_version_and_rechecked_live():
    fake = Counting()
    server, relay = fake.server()
    async with Client(server, mode="legacy") as mcp:
        first = await search(mcp, {"query": "text"})
        wanted = ["/templates/sd15_simple.json", "/templates/video_wan.json", "/templates/flux_custom.json"]
        assert sorted(p for p in fake.fetched if p != "/templates/index.mcp.json") == sorted(wanted)
        assert relay.template_requirements.version == "0.11.66" and len(relay.template_requirements) == 3
        assert first["results"][0]["runnability"] == {"runnable": True}

        # The same version: nothing fetched again, but the check is against what is on disk now.
        fake.fetched.clear()
        fake.table["/models/checkpoints"] = httpx2.Response(200, json=[])
        again = await search(mcp, {"query": "text"})
        assert [p for p in fake.fetched if p != "/templates/index.mcp.json"] == []
        sd15 = next(h for h in again["results"] if h["name"] == "sd15_simple")
        assert sd15["runnability"]["missing_models"] == {"count": 1, "first": ["sd15.safetensors"]}

        # Another templates version empties the cache and fetches again.
        fake.stats["system"]["installed_templates_version"] = "0.11.67"
        await search(mcp, {"query": "text"})
        assert sorted(p for p in fake.fetched if p != "/templates/index.mcp.json") == sorted(wanted)
        assert relay.template_requirements.version == "0.11.67" and len(relay.template_requirements) == 3


async def test_template_requirements_are_not_cached_without_a_templates_version():
    fake = Counting()
    del fake.stats["system"]["installed_templates_version"]
    server, relay = fake.server()
    async with Client(server, mode="legacy") as mcp:
        await search(mcp, {"query": "flux"})
        await search(mcp, {"query": "flux"})
    assert fake.fetched.count("/templates/flux_custom.json") == 2
    assert len(relay.template_requirements) == 0


def test_the_template_cache_is_bounded_and_drops_the_least_recently_used():
    cache = tools_introspection.TemplateCache(max_entries=2)
    needs = tools_introspection._requirements({"nodes": [node("SaveImage")]})
    cache.put("1", "a", needs)
    cache.put("1", "b", needs)
    assert cache.get("1", "a") is needs  # a is now the most recently used
    cache.put("1", "c", needs)
    assert (cache.get("1", "b"), len(cache)) == (None, 2)
    assert cache.get("2", "a") is None  # another version is never answered from this one
    cache.put("2", "d", needs)
    assert (cache.get("1", "a"), cache.get("2", "d"), len(cache)) == (None, needs, 1)


async def _stalled_template() -> httpx2.Response:
    await asyncio.sleep(60)
    raise AssertionError("the template fetch was waited for")


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (httpx2.Response(500), "comfyui_http_error"),
        (httpx2.Response(200, json={"no": "nodes"}), "comfyui_bad_response"),
        (httpx2.Response(200, json={"nodes": [{"type": "LoadImage", "inputs": 5}]}), "comfyui_bad_response"),
        (_stalled_template, "timeout"),
    ],
    ids=["http-error", "no-nodes", "unreadable", "stalled"],
)
async def test_a_template_that_cannot_be_fetched_is_unchecked_and_runnable_only_leaves_it_out(
    answer, reason, monkeypatch
):
    monkeypatch.setattr(tools_introspection, "TEMPLATE_FETCH_SECONDS", 0.5)
    overrides = {"/templates/flux_custom.json": answer}
    got = await ok("template_search", {"query": "text"}, **overrides)
    flux = next(h for h in got["results"] if h["name"] == "flux_custom")
    assert flux["runnability"] == {"runnable": None, "unchecked": reason}
    assert (got["unchecked"], got["total_matches"]) == (1, 3)
    # The others are checked as usual.
    assert {h["name"]: h["runnability"]["runnable"] for h in got["results"]} == {
        "sd15_simple": True,
        "video_wan": True,
        "flux_custom": None,
    }
    only = await ok("template_search", {"query": "text", "runnable_only": True}, **overrides)
    assert [h["name"] for h in only["results"]] == ["sd15_simple", "video_wan"]
    assert (only["unchecked"], only["hidden_not_runnable"], only["total_matches"]) == (1, 0, 2)


async def _stalled_folder() -> httpx2.Response:
    await asyncio.sleep(60)
    raise AssertionError("the folder listing was waited for")


@pytest.mark.parametrize(
    ("answer", "reason"),
    [(httpx2.Response(500), "comfyui_http_error"), (_stalled_folder, "timeout")],
    ids=["http-error", "stalled"],
)
async def test_a_model_folder_that_cannot_be_listed_leaves_only_its_templates_unchecked(answer, reason, monkeypatch):
    monkeypatch.setattr(tools_introspection, "MODEL_FOLDERS_SECONDS", 0.5)
    overrides = {"/models/checkpoints": answer}
    got = await ok("template_search", {"query": "text"}, **overrides)
    # sd15_simple and flux_custom declare checkpoints; video_wan declares no model.
    assert {h["name"]: h["runnability"] for h in got["results"]} == {
        "video_wan": {"runnable": True},
        "sd15_simple": {"runnable": None, "unchecked": reason},
        "flux_custom": {"runnable": None, "unchecked": reason},
    }
    assert got["unchecked"] == 2
    only = await ok("template_search", {"query": "text", "runnable_only": True}, **overrides)
    assert [h["name"] for h in only["results"]] == ["video_wan"]
    assert (only["unchecked"], only["total_matches"]) == (2, 1)
    # template_get still fails on it, as it always has: there the check is the answer, not enrichment.
    if reason != "timeout":
        assert (await error("template_get", {"name": "sd15_simple"}, **overrides))["code"] == reason


async def _stalled_object_info() -> httpx2.Response:
    await asyncio.sleep(60)
    raise AssertionError("/object_info was waited for")


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (httpx2.Response(500), "comfyui_http_error"),
        (httpx2.Response(200, json=["KSampler"]), "comfyui_bad_response"),
        (_stalled_object_info, "timeout"),
    ],
    ids=["http-error", "malformed", "stalled"],
)
async def test_template_search_answers_unchecked_when_object_info_fails(answer, reason, monkeypatch):
    monkeypatch.setattr(tools_introspection, "OBJECT_INFO_SECONDS", 0.5)
    got = await ok("template_search", {"query": "text"}, **{"/object_info": answer})
    assert {h["name"] for h in got["results"]} == {"sd15_simple", "flux_custom", "video_wan"}
    assert {h["runnability"]["unchecked"] for h in got["results"]} == {reason}
    assert {h["runnability"]["runnable"] for h in got["results"]} == {None}
    assert got["unchecked"] == 3
    only = await ok("template_search", {"query": "text", "runnable_only": True}, **{"/object_info": answer})
    assert (only["results"], only["unchecked"]) == ([], 3)


async def test_concurrent_cold_searches_share_one_limit_on_template_fetches():
    index = [{"title": "T", "templates": [{"name": f"t{i}", "title": "thing"} for i in range(20)]}]
    workflows = {f"/templates/t{i}.json": httpx2.Response(200, json={"nodes": [node("SaveImage")]}) for i in range(20)}
    fake = Counting(**{"/templates/index.json": httpx2.Response(200, json=index)})
    in_flight, peak = 0, 0

    def slow(response: httpx2.Response):
        async def answer() -> httpx2.Response:
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.02)
            in_flight -= 1
            return response

        return answer

    fake.table.update({path: slow(r) for path, r in workflows.items()})
    server, _ = fake.server()
    async with Client(server, mode="legacy") as mcp:
        got = await asyncio.gather(*(search(mcp, {"query": "thing", "limit": 20}) for _ in range(3)))
    assert peak == tools_introspection.FETCH_CONCURRENCY
    assert all(g["unchecked"] == 0 and len(g["results"]) == 20 for g in got)
    # Each template is read about once, not once per search.
    workflow_fetches = [p for p in fake.fetched if p in workflows]
    assert len(workflow_fetches) <= 20 + tools_introspection.FETCH_CONCURRENCY


async def test_a_short_search_is_not_starved_by_a_long_cold_one(monkeypatch):
    monkeypatch.setattr(tools_introspection, "TEMPLATE_FETCH_SECONDS", 1.0)
    index = [
        {"title": "A", "templates": [{"name": f"a{i}", "title": "alpha"} for i in range(200)]},
        {"title": "B", "templates": [{"name": f"b{i}", "title": "beta"} for i in range(2)]},
    ]
    fake = Counting(**{"/templates/index.json": httpx2.Response(200, json=index)})

    async def slow() -> httpx2.Response:
        await asyncio.sleep(0.1)
        return httpx2.Response(200, json={"nodes": [node("SaveImage")]})

    fake.table.update({f"/templates/{t['name']}.json": slow for c in index for t in c["templates"]})
    server, _ = fake.server()
    async with Client(server, mode="legacy") as mcp:
        long = asyncio.ensure_future(search(mcp, {"query": "alpha", "limit": 20}))
        await asyncio.sleep(0.02)
        short = await search(mcp, {"query": "beta"})
        await long
    assert short["unchecked"] == 0
    assert [h["runnability"] for h in short["results"]] == [{"runnable": True}] * 2


MCP_INDEX = [
    {
        "category": "Video",
        "templates": [
            {
                "name": "video_wan",
                "task": "Image to Video",
                "description": "Animate a still.",
                "io": {"inputs": ["image: The first frame"], "outputs": ["video: The clip"]},
                "capabilities": {"workflow": ["image-to-video"], "model_options": {"Node": ["a", "b"]}},
                "recommend": "high",
                "freshness": "recent",
            },
            # The index.json flags it openSource: false.
            {"name": "api_dalle", "task": "Text to Image"},
        ],
    }
]
MCP_PATH = "/templates/index.mcp.json"


async def test_template_search_reads_the_agent_index_when_comfyui_serves_it():
    mcp = {MCP_PATH: httpx2.Response(200, json=MCP_INDEX)}
    # "still" is only in index.mcp.json's text.
    got = await ok("template_search", {"query": "animate a still"}, **mcp)
    assert got["source"]["index"] == "index.mcp.json"
    (hit,) = got["results"]
    assert {k: hit[k] for k in ("name", "task", "inputs", "outputs", "capabilities", "recommend", "freshness")} == {
        "name": "video_wan",
        "task": "Image to Video",
        "inputs": ["image: The first frame"],
        "outputs": ["video: The clip"],
        "capabilities": ["image-to-video"],
        "recommend": "high",
        "freshness": "recent",
    }
    # A template the agent index doesn't list is still found, from index.json alone.
    other = await ok("template_search", {"query": "SD1.5"}, **mcp)
    assert other["results"][0]["name"] == "sd15_simple" and "task" not in other["results"][0]
    # The agent index has no openSource flag, so listing a partner-API template there doesn't unhide it.
    assert (await ok("template_search", {"query": "dall"}, **mcp))["results"] == []


async def test_template_search_caps_every_string_the_agent_index_gives():
    huge = "z" * 10_000
    entry = {
        "name": "video_wan",
        "task": huge,
        "recommend": huge,
        "freshness": huge,
        "description": huge,
        "io": {"inputs": [huge] * 50, "outputs": [huge] * 50},
        "capabilities": {"workflow": [huge] * 50},
    }
    got = await ok(
        "template_search", {"query": "wan"}, **{MCP_PATH: httpx2.Response(200, json=[{"templates": [entry]}])}
    )
    (hit,) = got["results"]
    assert len(hit["description"]) == 240
    assert len(hit["inputs"]) == len(hit["outputs"]) == 4 and len(hit["capabilities"]) == 8
    assert {len(s) for s in hit["inputs"] + hit["outputs"]} == {120}
    assert {len(s) for s in [hit["task"], hit["recommend"], hit["freshness"], *hit["capabilities"]]} == {40}


async def _stall() -> httpx2.Response:
    await asyncio.sleep(60)
    raise AssertionError("the agent index was waited for")


async def _read_timeout() -> httpx2.Response:
    raise httpx2.ReadTimeout("slow")


@pytest.mark.parametrize(
    "answer",
    [
        httpx2.Response(404),
        httpx2.Response(500),
        httpx2.Response(200, text="<html></html>"),
        httpx2.Response(200, json={"no": "list"}),
        httpx2.Response(200, json=[{"templates": [{"name": "not_in_index_json", "task": "x"}]}]),
        _read_timeout,
        _stall,
    ],
    ids=["missing", "server-error", "not-json", "wrong-shape", "nothing-joined", "read-timeout", "stalled"],
)
async def test_template_search_falls_back_to_index_json(answer, monkeypatch):
    monkeypatch.setattr(tools_introspection, "AGENT_INDEX_SECONDS", 0.2)
    got = await ok("template_search", {"query": "wan"}, **{MCP_PATH: answer})
    assert got["source"]["index"] == "index.json"
    (hit,) = got["results"]
    assert hit["name"] == "video_wan" and "task" not in hit


@pytest.mark.parametrize("tool", ["node_search", "template_search"])
@pytest.mark.parametrize("query", ["!!!", " - ", "|"])
async def test_a_query_with_nothing_to_search_for_is_invalid(tool, query):
    err = await error(tool, {"query": query})
    assert (err["code"], err["retryable"]) == ("invalid_query", False)


async def test_template_get_refuses_a_workflow_too_large_to_return():
    big = {"nodes": [node("SaveImage")], "extra": {"blob": "x" * 90_000}}
    overrides = {"/templates/sd15_simple.json": httpx2.Response(200, json=big)}
    err = await error("template_get", {"name": "sd15_simple"}, **overrides)
    assert err["code"] == "workflow_too_large"
    assert err["limit"] == 80_000 and err["size"] > 90_000
    assert "include_workflow=false" in err["message"]
    lean = await ok("template_get", {"name": "sd15_simple", "include_workflow": False}, **overrides)
    assert lean["runnability"]["runnable"] is True


async def test_template_dot_segment_directories_and_names_are_never_requested():
    seen = []
    workflow = {"nodes": [node("CheckpointLoaderSimple", models=[model("x.safetensors", "..")])]}
    index = [{"title": "T", "templates": [{"name": "..", "title": "dots"}, {"name": "dots", "title": "dots"}]}]
    table = routes(
        **{
            "/templates/index.json": httpx2.Response(200, json=index),
            "/templates/dots.json": httpx2.Response(200, json=workflow),
        }
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.raw_path.decode())
        return table.get(request.url.raw_path.decode(), httpx2.Response(404))

    client = ComfyUIClient("http://comfyui.test:8188", transport=httpx2.MockTransport(handler))
    server, _ = build_server(settings(profiles=("read",)), comfyui=client)
    async with Client(server, mode="legacy") as mcp:
        result = await mcp.call_tool("template_search", {"query": "dots"})
        detail = await mcp.call_tool("template_get", {"name": "dots", "include_workflow": False})
    assert not result.is_error, result.content[0].text
    assert [h["name"] for h in result.structured_content["results"]] == ["dots"]
    assert result.structured_content["results"][0]["runnability"]["missing_models"]["count"] == 1
    assert detail.structured_content["runnability"]["missing_models"][0]["folder_known"] is False
    assert not [p for p in seen if p.startswith("/models/") or p == "/templates/...json"]


async def test_template_get_returns_the_workflow_and_its_check():
    got = await ok("template_get", {"name": "sd15_simple"})
    assert got["workflow"] == TEMPLATES["sd15_simple"]
    assert got["runnability"]["runnable"] is True
    assert (got["author"], got["min_comfyui_version"]) == ("ComfyUI", "0.3.0")
    assert got["source"]["package"] == "comfyui-workflow-templates"
    lean = await ok("template_get", {"name": "flux_custom.json", "include_workflow": False})
    assert "workflow" not in lean and lean["runnability"]["runnable"] is False


async def test_an_unknown_template_suggests_close_names():
    err = await error("template_get", {"name": "sd15_simpel"})
    assert err["code"] == "unknown_template"
    assert err["suggestions"][0] == {"name": "sd15_simple", "title": "SD1.5: Text to Image"}


# -- malformed answers are comfyui_bad_response -------------------------------------


@pytest.mark.parametrize(
    ("tool", "args", "path", "body"),
    [
        ("node_search", {"query": "x"}, "/object_info", ["KSampler"]),
        ("node_search", {"query": "x"}, "/object_info", {"KSampler": "not an object"}),
        ("node_describe", {"class_type": "KSampler"}, "/object_info/KSampler", {"KSampler": {"input": []}}),
        ("node_describe", {"class_type": "KSampler"}, "/object_info/KSampler", {"Other": {}}),
        ("model_list", {}, "/models", {"checkpoints": []}),
        ("model_list", {}, "/models", [1, 2]),
        ("model_list", {}, "/models/checkpoints", [{"name": "x"}]),
        ("template_search", {"query": "x"}, "/templates/index.json", {"templates": []}),
        ("template_search", {"query": "x"}, "/templates/index.json", [{"templates": [{"title": "no name"}]}]),
        ("template_get", {"name": "flux_custom"}, "/templates/flux_custom.json", {"no": "nodes"}),
        ("template_get", {"name": "sd15_simple"}, "/templates/sd15_simple.json", []),
    ],
    ids=[
        "object-info-list",
        "object-info-entry",
        "describe-no-input",
        "describe-other-class",
        "models-object",
        "models-not-strings",
        "folder-not-strings",
        "index-object",
        "index-no-name",
        "template-no-nodes",
        "template-list",
    ],
)
async def test_a_malformed_answer_is_a_bad_response(tool, args, path, body):
    err = await error(tool, args, **{path: httpx2.Response(200, json=body)})
    assert (err["code"], err["retryable"]) == ("comfyui_bad_response", False)


async def test_a_template_missing_from_comfyui_is_an_http_error():
    err = await error("template_get", {"name": "sd15_simple"}, **{"/templates/sd15_simple.json": httpx2.Response(404)})
    assert (err["code"], err["status"]) == ("comfyui_http_error", 404)


# -- read-only, and nothing but ComfyUI ---------------------------------------------


async def test_every_introspection_tool_is_read_only_and_only_gets_from_comfyui():
    seen = []
    table = routes()

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append((request.method, request.url.host))
        return table.get(request.url.raw_path.decode(), httpx2.Response(404))

    client = ComfyUIClient("http://comfyui.test:8188", transport=httpx2.MockTransport(handler))
    server, _ = build_server(settings(profiles=("read",)), comfyui=client)
    async with Client(server, mode="legacy") as mcp:
        tools = {t.name: t for t in (await mcp.list_tools()).tools}
        for name, args in [
            ("node_search", {"query": "checkpoint"}),
            ("node_describe", {"class_type": "KSampler"}),
            ("model_list", {}),
            ("template_search", {"query": "image", "include_partner_api": True}),
            ("template_get", {"name": "flux_custom"}),
        ]:
            assert not (await mcp.call_tool(name, args)).is_error, name
            assert tools[name].annotations.read_only_hint is True
            assert tools[name].annotations.destructive_hint is False
            assert tools[name].output_schema is not None
    assert {method for method, _ in seen} == {"GET"}
    assert {host for _, host in seen} == {"comfyui.test"}
