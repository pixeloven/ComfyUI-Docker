"""The pre-submission workflow check (comfyrelay/workflow.py): structure, classes, links, and partner-API nodes.
Input types and values are ComfyUI's to check at /prompt, so nothing here tests them."""

from __future__ import annotations

import pytest
from comfyrelay.workflow import MAX_NODES, partner_api_nodes, partner_signals, validate
from relay_helpers import WORKFLOW_OBJECT_INFO as INFO


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


def test_values_and_types_are_left_to_comfyui():
    """A free-form COMBO value, a wrong-typed link, a missing input: /prompt decides all of these (a CustomCombo
    takes any value though its options list is empty, which a copied check refused)."""
    graph = {
        "1": {"class_type": "CustomCombo", "inputs": {"choice": "my own option"}},
        "2": {"class_type": "PreviewAny", "inputs": {"source": ["1", 0]}},
        "3": {"class_type": "SaveImage", "inputs": {"images": ["1", 1]}},  # INT into IMAGE, no prefix
    }
    assert validate(graph, INFO).valid


def test_unknown_node_class_suggests_the_near_names():
    graph = t1()
    graph["3"]["class_type"] = "ImageInvertt"
    [error] = errors(graph)
    assert error["type"] == "missing_node_type"
    assert (error["node_id"], error["class_type"]) == ("3", "ImageInvertt")
    assert error["message"] == "Node 'ImageInvertt' not found. The custom node may not be installed."
    assert "ImageInvert" in error["expected"]


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


@pytest.mark.parametrize("link", [["2"], ["2", 0, 1], [2, 0], ["2", "0"], ["2", True], ["a", "b"]])
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
    graph["9"] = {"class_type": "ImageInvert", "inputs": {"image": ["404", 0]}}  # a bad link, but nothing uses it
    assert errors(graph) == []
    assert [(w["type"], w["node_id"]) for w in warnings(graph)] == [("not_connected_to_output", "9")]


def test_every_problem_is_reported_at_once():
    graph = t1()
    graph["2"]["class_type"] = "ImageScaler"
    graph["3"]["inputs"]["image"] = ["1", 5]
    graph["5"] = {"class_type": "PreviewImage", "inputs": {"images": ["9", 0]}}
    graph["6"] = {"class_type": "PreviewImage", "inputs": {"images": ["3"]}}
    assert sorted((e["node_id"], e["type"]) for e in errors(graph)) == [
        ("2", "missing_node_type"),
        ("3", "linked_output_missing"),
        ("5", "linked_node_missing"),
        ("6", "bad_linked_input"),
    ]


def test_a_graph_over_the_node_cap_is_refused():
    graph = {str(i): {"class_type": "ImageInvert", "inputs": {}} for i in range(MAX_NODES + 1)}
    [error] = errors(graph)
    assert (error["type"], error["got"], error["expected"]) == (
        "workflow_too_large",
        MAX_NODES + 1,
        {"max_nodes": 2000},
    )


def test_a_list_value_that_is_not_a_link_does_not_pull_in_a_node():
    """_upstream follows only real links, so a stray list does not make an unrelated node 'needed'."""
    graph = t1()
    graph["9"] = {"class_type": "ImageInvert", "inputs": {}}
    graph["4"]["inputs"]["filename_prefix"] = ["9", "x"]
    assert ("not_connected_to_output", "9") in [(w["type"], w["node_id"]) for w in warnings(graph)]


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


# -- partner-API nodes --------------------------------------------------------------


def test_partner_api_nodes_are_found_by_any_signal():
    graph = {
        "1": {"class_type": "ClaudeNode", "inputs": {}},
        "2": {"class_type": "ByteDanceCreateImageAsset", "inputs": {}},
        "3": {"class_type": "ImageInvert", "inputs": {}},
    }
    found = partner_api_nodes(graph, INFO)
    assert [(n["node_id"], n["class_type"], n["signals"]) for n in found] == [
        ("1", "ClaudeNode", ["api_node", "comfy_org_credentials", "comfy_api_nodes"]),
        # api_node is false, but it asks for the Comfy.org credentials and lives in comfy_api_nodes
        ("2", "ByteDanceCreateImageAsset", ["comfy_org_credentials", "comfy_api_nodes"]),
    ]
    assert validate(graph, INFO).partner_api_nodes == found


@pytest.mark.parametrize(
    ("spec", "signals"),
    [
        ({"api_node": 1}, ["api_node"]),  # truthy, not only True
        ({"python_module": "comfy_api_nodes.nodes_openai"}, ["comfy_api_nodes"]),
        ({"python_module": "custom_nodes.my_pack"}, []),
        ({"input": {"hidden": {"key": ["API_KEY_COMFY_ORG"]}}}, ["comfy_org_credentials"]),
        ({"input": {"hidden": {"odd": [{"a": 1}], "odder": {"b": 2}, "empty": []}}}, []),  # no TypeError
        ({"input": "not an object"}, []),
        (None, []),
    ],
)
def test_partner_signals(spec, signals):
    assert partner_signals(spec) == signals
