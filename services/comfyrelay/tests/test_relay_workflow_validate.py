"""The static workflow check (comfyrelay/workflow.py), against node definitions taken from a real v0.37.0
/object_info (object_info_v0.37.0.json beside this file; LoadImage's file list is replaced by two names)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from comfyrelay.workflow import expand_inputs, partner_api_nodes, types_compatible, validate

INFO = json.loads((Path(__file__).parent / "object_info_v0.37.0.json").read_text())


def t1() -> dict:
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": "harness-input.png"}},
        "2": {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["1", 0],
                "upscale_method": "nearest-exact",
                "width": 256,
                "height": 256,
                "crop": "disabled",
            },
        },
        "3": {"class_type": "ImageInvert", "inputs": {"image": ["2", 0]}},
        "4": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "t1_"}},
    }


def errors(graph: dict) -> list[dict]:
    return [p.as_dict() for p in validate(graph, INFO).errors]


def warnings(graph: dict) -> list[dict]:
    return [p.as_dict() for p in validate(graph, INFO).warnings]


def test_a_good_graph_is_valid():
    report = validate(t1(), INFO)
    assert report.valid and not report.errors and not report.warnings
    assert report.output_nodes == ["4"] and report.node_count == 4 and report.partner_api_nodes == []


def test_unknown_node_class_suggests_the_near_names():
    graph = t1()
    graph["3"]["class_type"] = "ImageInvertt"
    [error] = errors(graph)
    assert error["type"] == "missing_node_type"
    assert (error["node_id"], error["class_type"]) == ("3", "ImageInvertt")
    assert error["message"] == "Node 'ImageInvertt' not found. The custom node may not be installed."
    assert "ImageInvert" in error["expected"]


def test_missing_required_input():
    graph = t1()
    del graph["2"]["inputs"]["width"]
    [error] = errors(graph)
    assert error == {
        "type": "required_input_missing",
        "message": "Required input is missing",
        "node_id": "2",
        "class_type": "ImageScale",
        "input": "width",
        "details": "width",
        "expected": "INT",
    }


def test_type_mismatch_uses_comfyuis_wording():
    """The harness's T4 graph: LoadImage's MASK output wired into SaveImage's IMAGE input."""
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "harness-input.png"}},
        "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 1], "filename_prefix": "t4_"}},
    }
    [error] = errors(graph)
    assert error == {
        "type": "return_type_mismatch",
        "message": "Return type mismatch between linked nodes",
        "node_id": "2",
        "class_type": "SaveImage",
        "input": "images",
        "details": "images, received_type(MASK) mismatch input_type(IMAGE)",
        "expected": "IMAGE",
        "got": "MASK",
    }


def test_a_string_linked_into_an_int_is_a_mismatch():
    graph = {
        "1": {"class_type": "PrimitiveString", "inputs": {"value": "64"}},
        "2": {"class_type": "EmptyImage", "inputs": {"width": ["1", 0], "height": 64, "batch_size": 1, "color": 0}},
        "3": {"class_type": "PreviewImage", "inputs": {"images": ["2", 0]}},
    }
    [error] = errors(graph)
    assert (error["type"], error["expected"], error["got"]) == ("return_type_mismatch", "INT", "STRING")
    graph["1"] = {"class_type": "PrimitiveInt", "inputs": {"value": 64}}
    assert errors(graph) == []


def test_a_combo_value_not_in_the_list():
    graph = t1()
    graph["2"]["inputs"]["upscale_method"] = "nearest"
    [error] = errors(graph)
    assert (error["type"], error["message"], error["input"]) == (
        "value_not_in_list",
        "Value not in list",
        "upscale_method",
    )
    assert error["expected"] == ["nearest-exact", "bilinear", "area", "bicubic", "lanczos"]
    assert error["got"] == "nearest"
    assert "did you mean 'nearest-exact'" in error["details"]


def test_a_file_picker_value_not_listed_is_only_a_warning():
    """LoadImage checks its file itself when ComfyUI gets the graph, and may accept what /object_info does not
    list (a subfolder, an annotated path), so this is ComfyUI's call."""
    graph = t1()
    graph["1"]["inputs"]["image"] = "sub/elsewhere.png"
    assert errors(graph) == []
    [warning] = warnings(graph)
    assert (warning["type"], warning["node_id"], warning["input"]) == ("value_not_in_list", "1", "image")


@pytest.mark.parametrize(
    ("value", "kind"),
    [("wide", "invalid_input_type"), (-1, "value_smaller_than_min"), (99_999, "value_bigger_than_max")],
)
def test_numbers_are_converted_and_bounded(value, kind):
    graph = t1()
    graph["2"]["inputs"]["width"] = value
    [error] = errors(graph)
    assert (error["type"], error["input"]) == (kind, "width")


def test_a_number_as_a_string_converts_as_comfyui_does():
    graph = t1()
    graph["2"]["inputs"]["width"] = "256"
    assert errors(graph) == []


def test_a_link_to_a_node_that_is_not_there():
    graph = t1()
    graph["3"]["inputs"]["image"] = ["7", 0]
    [error] = errors(graph)
    assert (error["type"], error["node_id"], error["input"], error["got"]) == (
        "linked_node_missing",
        "3",
        "image",
        ["7", 0],
    )


def test_a_link_to_an_output_the_node_does_not_have():
    graph = t1()
    graph["3"]["inputs"]["image"] = ["2", 1]
    [error] = errors(graph)
    assert (error["type"], error["expected"], error["got"]) == ("linked_output_missing", ["IMAGE"], ["2", 1])


@pytest.mark.parametrize("link", [["2"], ["2", 0, 1], [2, 0]])
def test_a_malformed_link(link):
    graph = t1()
    graph["3"]["inputs"]["image"] = link
    assert [e["type"] for e in errors(graph)] == ["bad_linked_input"]


def test_a_graph_with_no_output_node():
    graph = t1()
    del graph["4"]
    [error] = errors(graph)
    assert (error["type"], error["message"]) == ("prompt_no_outputs", "Prompt has no outputs")


def test_nodes_no_output_needs_get_a_warning_not_an_error():
    graph = t1()
    graph["9"] = {"class_type": "ImageInvert", "inputs": {}}  # missing its input, but nothing uses it
    assert errors(graph) == []
    assert [(w["type"], w["node_id"]) for w in warnings(graph)] == [("not_connected_to_output", "9")]


def test_an_unknown_input_name_is_a_warning_with_suggestions():
    graph = t1()
    graph["2"]["inputs"]["widht"] = 10
    [warning] = warnings(graph)
    assert (warning["type"], warning["input"], warning["expected"]) == ("unknown_input", "widht", ["width"])


def test_a_constant_for_a_socket_is_a_warning():
    graph = t1()
    graph["3"]["inputs"]["image"] = "picture.png"
    found = warnings(graph)
    assert ("constant_for_link", "3", "IMAGE") in [(w["type"], w["node_id"], w.get("expected")) for w in found]
    # and nodes 1 and 2 now feed nothing
    assert [w["node_id"] for w in found if w["type"] == "not_connected_to_output"] == ["1", "2"]


def test_every_problem_is_reported_at_once():
    graph = t1()
    graph["2"]["inputs"]["upscale_method"] = "nope"
    del graph["2"]["inputs"]["height"]
    del graph["4"]["inputs"]["filename_prefix"]
    assert sorted((e["node_id"], e["type"]) for e in errors(graph)) == [
        ("2", "required_input_missing"),
        ("2", "value_not_in_list"),
        ("4", "required_input_missing"),
    ]


# -- what is not an API-format graph --------------------------------------------


def test_the_ui_format_is_refused_with_directions():
    [error] = errors({"nodes": [], "links": [], "version": 0.4})
    assert error["type"] == "invalid_workflow" and "Export (API)" in error["message"]


def test_a_prompt_request_body_is_refused_with_directions():
    [error] = errors({"prompt": t1(), "client_id": "x"})
    assert error["type"] == "invalid_workflow" and '"prompt" key' in error["message"]


@pytest.mark.parametrize(
    ("graph", "kind"),
    [
        ({}, "invalid_workflow"),
        ({"1": "LoadImage"}, "invalid_workflow"),
        ({"1": {"inputs": {}}}, "missing_node_type"),
        ({"1": {"class_type": "LoadImage", "inputs": ["image"]}}, "invalid_workflow"),
    ],
)
def test_malformed_graphs(graph, kind):
    assert [e["type"] for e in errors(graph)] == [kind]


# -- ComfyUI's dynamic V3 inputs ---------------------------------------------------


def test_a_dynamic_combo_adds_the_chosen_options_inputs():
    spec = INFO["ResizeImageMaskNode"]["input"]
    expanded = expand_inputs(spec, {"resize_type": "scale dimensions"})
    assert {"resize_type", "resize_type.width", "resize_type.height", "resize_type.crop"} <= set(expanded["required"])
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "harness-input.png"}},
        "2": {
            "class_type": "ResizeImageMaskNode",
            "inputs": {
                "input": ["1", 0],
                "resize_type": "scale dimensions",
                "resize_type.width": 64,
                "resize_type.height": 64,
                "resize_type.crop": "center",
                "scale_method": "area",
            },
        },
        "3": {"class_type": "PreviewImage", "inputs": {"images": ["2", 0]}},
    }
    assert errors(graph) == []
    del graph["2"]["inputs"]["resize_type.height"]
    assert [(e["type"], e["input"]) for e in errors(graph)] == [("required_input_missing", "resize_type.height")]
    graph["2"]["inputs"]["resize_type"] = "sideways"
    [error] = errors(graph)
    assert (error["type"], error["input"]) == ("value_not_in_list", "resize_type")
    assert "scale dimensions" in error["expected"]


def test_a_left_out_dynamic_combo_is_an_error_here():
    """ComfyUI's check lets this through, and the node then raises TypeError when it runs."""
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "harness-input.png"}},
        "2": {"class_type": "ResizeImageMaskNode", "inputs": {"input": ["1", 0], "scale_method": "area"}},
        "3": {"class_type": "PreviewImage", "inputs": {"images": ["2", 0]}},
    }
    assert [(e["type"], e["input"]) for e in errors(graph)] == [("required_input_missing", "resize_type")]


def test_an_autogrow_input_takes_numbered_inputs():
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "harness-input.png"}},
        "2": {"class_type": "BatchImagesNode", "inputs": {"images.image0": ["1", 0], "images.image1": ["1", 0]}},
        "3": {"class_type": "PreviewImage", "inputs": {"images": ["2", 0]}},
    }
    assert errors(graph) == [] and warnings(graph) == []
    graph["2"]["inputs"] = {"images.image1": ["1", 0]}
    assert [(e["type"], e["input"]) for e in errors(graph)] == [("required_input_missing", "images.image0")]
    graph["2"]["inputs"] = {"images.image0": ["1", 1]}
    assert [(e["type"], e["input"], e["got"]) for e in errors(graph)] == [
        ("return_type_mismatch", "images.image0", "MASK")
    ]


def test_matchtype_takes_either_of_its_types():
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "harness-input.png"}},
        "2": {
            "class_type": "ResizeImageMaskNode",
            "inputs": {
                "input": ["1", 1],
                "resize_type": "scale by multiplier",
                "resize_type.multiplier": 0.5,
                "scale_method": "area",
            },
        },
        "3": {"class_type": "MaskPreview", "inputs": {"mask": ["2", 0]}},
    }
    assert errors(graph) == []


@pytest.mark.parametrize(
    ("received", "wanted", "ok"),
    [
        ("IMAGE", "IMAGE", True),
        ("MASK", "IMAGE", False),
        ("*", "IMAGE", True),
        ("IMAGE", "*", True),
        ("INT", "FLOAT,INT", True),
        ("STRING,BOOLEAN", "STRING,INT", True),
        ("COMFY_MATCHTYPE_V3", "LATENT", True),
        (["a", "b"], "COMBO", True),
        ("STRING", ["a", "b"], False),
    ],
)
def test_type_compatibility_follows_comfyui(received, wanted, ok):
    assert types_compatible(received, wanted) is ok


# -- partner-API nodes --------------------------------------------------------------


def test_partner_api_nodes_are_found_by_either_signal():
    graph = {
        "1": {"class_type": "ClaudeNode", "inputs": {}},
        "2": {"class_type": "ByteDanceCreateImageAsset", "inputs": {}},
        "3": {"class_type": "ImageInvert", "inputs": {}},
    }
    found = partner_api_nodes(graph, INFO)
    assert [(n["node_id"], n["class_type"], n["signals"]) for n in found] == [
        ("1", "ClaudeNode", ["api_node", "comfy_org_credentials"]),
        # api_node is false, but it asks for the Comfy.org credentials
        ("2", "ByteDanceCreateImageAsset", ["comfy_org_credentials"]),
    ]
    assert validate(graph, INFO).partner_api_nodes == found
