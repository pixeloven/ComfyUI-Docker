"""The checks a workflow gets before it is submitted, and only those ComfyUI cannot make for us.

An API-format workflow maps node ids to `{"class_type": ..., "inputs": {...}}`.
An input's value is a constant, or a link `["<node id>", <output index>]`.

ComfyUI (v0.37.0) has no dry run: its only complete check is `/prompt`, which
queues the graph when it passes. And /object_info cannot show a node's own
validate_inputs, so a copy of ComfyUI's type, COMBO and bounds checks refuses
graphs ComfyUI accepts (a CustomCombo's value is free-form, though its
options list is empty) and drifts with every pin. So those checks are
ComfyUI's, made when the graph is submitted (workflow_run maps its per-node
errors). What stays here:

    invalid_workflow        not an API-format graph at all (a UI-format save,
                            a /prompt body, a node that is not an object)
    workflow_too_large      more than MAX_NODES nodes
    missing_node_type       a class not in /object_info, with near names
                            (/prompt reports this without saying which node)
    prompt_no_outputs       nothing in the graph is an output node
    bad_linked_input        a link that is not ["<node id>", <output index>]
    linked_node_missing     a link to a node the graph does not have
    linked_output_missing   a link to an output its node does not have
                            (ComfyUI raises on these three, not a clean error)

plus partner-API detection (`partner_api_nodes`), which workflow_run refuses
on, and a warning for nodes no output depends on (ComfyUI will not run them).
Like ComfyUI, links are checked on the nodes an output depends on.

What this does not do: apply ComfyUI's node replacements (/node_replacements,
which /prompt applies to a class that is no longer installed). An old class
name is `missing_node_type` here; the class that replaced it is the one to use.
"""

from __future__ import annotations

import difflib
from dataclasses import asdict, dataclass
from typing import Any

# ComfyUI's dynamic V3 inputs (comfy_api/latest/_io.py), which expand into
# more inputs according to the values the graph gives them. Inside one, every
# input's key is its path joined with dots (`qualified`, ComfyUI's
# finalize_prefix): a DynamicCombo `resize_type` set to "scale dimensions" adds
# `resize_type.width`, an Autogrow `images` with prefix "image" takes
# `images.image0`, `images.image1` and so on. This module owns that naming;
# node_describe (tools_introspection.py) renders it with the same helpers.
AUTOGROW = "COMFY_AUTOGROW_V3"
DYNAMIC_COMBO = "COMFY_DYNAMICCOMBO_V3"
DYNAMIC_SLOT = "COMFY_DYNAMICSLOT_V3"
MATCH_TYPE = "COMFY_MATCHTYPE_V3"

# The hidden inputs through which ComfyUI hands a node the user's Comfy.org
# credentials, which pay for partner-API calls.
COMFY_ORG_CREDENTIALS = frozenset({"AUTH_TOKEN_COMFY_ORG", "API_KEY_COMFY_ORG"})
# The package ComfyUI's own partner-API nodes live in.
API_NODES_MODULE = "comfy_api_nodes."

# The most nodes workflow_run submits. ComfyUI walks a graph in one thread; a
# 10,000-node graph wedged its worker past what an interrupt could stop.
MAX_NODES = 2000

MAX_PROBLEMS = 100


@dataclass
class Problem:
    type: str
    message: str
    node_id: str | None = None
    class_type: str | None = None
    input: str | None = None
    details: str | None = None
    expected: Any = None
    got: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class Report:
    errors: list[Problem]
    warnings: list[Problem]
    partner_api_nodes: list[dict[str, Any]]
    output_nodes: list[str]
    node_count: int

    @property
    def valid(self) -> bool:
        return not self.errors


def _node_order(node_id: str) -> tuple[int, int | str]:
    return (0, int(node_id)) if node_id.isdigit() else (1, node_id)


def _is_link(value: Any) -> bool:
    """A well-formed link: ["<node id>", <output index>]. ComfyUI treats any list as a link, so a list that is not
    one is reported as a bad link, not taken as a value."""
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], (int, float))
        and not isinstance(value[1], bool)
    )


def qualified(path: list[str]) -> str:
    """A dynamic input's key in a graph: its path joined with dots, as ComfyUI's finalize_prefix joins it."""
    return ".".join(path)


def autogrow_names(template: dict[str, Any]) -> list[str] | None:
    """The inputs an Autogrow takes, unqualified and in order: its `names`, or `prefix` plus 0 to max - 1."""
    if isinstance(template.get("names"), list):
        return [str(n) for n in template["names"]]
    if isinstance(template.get("prefix"), str) and isinstance(template.get("max"), int):
        return [f"{template['prefix']}{i}" for i in range(template["max"])]
    return None


def autogrow_item(template: dict[str, Any]) -> tuple[Any, bool] | None:
    """What each of an Autogrow's inputs takes, and whether it sits in `required` (then its first `min` are)."""
    sections = template.get("input") if isinstance(template.get("input"), dict) else {}
    for section, specs in sections.items():
        if isinstance(specs, dict) and specs:
            return next(iter(specs.values())), section == "required"
    return None


def autogrow_min(template: dict[str, Any]) -> int:
    return template["min"] if isinstance(template.get("min"), int) else 1


def partner_signals(spec: Any) -> list[str]:
    """Why a node class spends partner-API credits, as /object_info shows it; [] when it does not.

        api_node               the class's API_NODE flag (what --disable-api-nodes and the editor's badge use)
        comfy_org_credentials  it asks for the user's Comfy.org credentials through a hidden input: how it pays
        comfy_api_nodes        it comes from ComfyUI's own partner-API package

    workflow_run refuses a graph with any; template runnability and node search flag the same classes.
    """
    if not isinstance(spec, dict):
        return []
    signals = []
    if spec.get("api_node"):
        signals.append("api_node")
    hidden = (spec.get("input") or {}).get("hidden") if isinstance(spec.get("input"), dict) else None
    types = set()
    for value in hidden.values() if isinstance(hidden, dict) else ():
        first = value[0] if isinstance(value, list) and value else value
        if isinstance(first, str):
            types.add(first)
    if types & COMFY_ORG_CREDENTIALS:
        signals.append("comfy_org_credentials")
    if str(spec.get("python_module") or "").startswith(API_NODES_MODULE):
        signals.append("comfy_api_nodes")
    return signals


def _suggest(word: str, choices: Any, n: int = 3) -> list[str]:
    return difflib.get_close_matches(str(word), [str(c) for c in choices], n=n, cutoff=0.6)


# -- the checks ---------------------------------------------------------------


def shape_problems(graph: Any) -> list[Problem]:
    """What stops `graph` being read as an API-format workflow at all."""
    if not isinstance(graph, dict) or not graph:
        return [Problem("invalid_workflow", "the workflow is empty: send an object of {node_id: node}")]
    if isinstance(graph.get("nodes"), list) and "links" in graph:
        return [
            Problem(
                "invalid_workflow",
                "this is a UI-format workflow (the editor's save file, with nodes and links lists). Send the API "
                'format instead: {"<node id>": {"class_type": "...", "inputs": {...}}}, which the editor '
                "exports as Export (API)",
            )
        ]
    wrapped = graph.get("prompt")
    if (
        set(graph) <= {"prompt", "client_id", "extra_data", "prompt_id"}
        and isinstance(wrapped, dict)
        and "class_type" not in wrapped
    ):
        return [
            Problem(
                "invalid_workflow",
                'this is a /prompt request body. Send the workflow itself: the value of its "prompt" key',
            )
        ]
    if len(graph) > MAX_NODES:
        return [
            Problem(
                "workflow_too_large",
                f"the workflow has {len(graph)} nodes; this server runs at most {MAX_NODES}",
                expected={"max_nodes": MAX_NODES},
                got=len(graph),
            )
        ]
    problems = []
    for node_id, node in graph.items():
        if not isinstance(node, dict):
            problems.append(
                Problem("invalid_workflow", f"node {node_id!r} is not an object", node_id=node_id, got=node)
            )
        elif not isinstance(node.get("class_type"), str) or not node["class_type"]:
            problems.append(
                Problem(
                    "missing_node_type",
                    f"Node 'ID #{node_id}' has no class_type. The workflow may be corrupted or a custom node is "
                    "missing.",
                    node_id=node_id,
                )
            )
        elif not isinstance(node.get("inputs", {}), dict):
            problems.append(
                Problem(
                    "invalid_workflow",
                    f'node {node_id!r} has "inputs" that is not an object',
                    node_id=node_id,
                    class_type=node["class_type"],
                )
            )
    return problems


def partner_api_nodes(graph: dict[str, Any], info: dict[str, Any]) -> list[dict[str, Any]]:
    """Nodes that call a paid partner API, as /object_info marks them (`partner_signals`). Any one signal is
    enough."""
    found = []
    for node_id, node in graph.items():
        spec = info.get(node.get("class_type")) if isinstance(node, dict) else None
        signals = partner_signals(spec)
        if signals:
            found.append(
                {
                    "node_id": node_id,
                    "class_type": node["class_type"],
                    "category": spec.get("category"),
                    "signals": signals,
                }
            )
    return sorted(found, key=lambda n: _node_order(n["node_id"]))


def validate(graph: dict[str, Any], info: dict[str, Any]) -> Report:
    """The structural problems in `graph`, the classes /object_info (`info`) lacks, and its partner-API nodes."""
    errors = shape_problems(graph)
    if errors:
        return Report(errors, [], [], [], len(graph) if isinstance(graph, dict) else 0)
    warnings: list[Problem] = []
    for node_id, node in graph.items():
        if node["class_type"] not in info:
            title = (node.get("_meta") or {}).get("title") or node["class_type"]
            errors.append(
                Problem(
                    "missing_node_type",
                    f"Node '{title}' not found. The custom node may not be installed.",
                    node_id=node_id,
                    class_type=node["class_type"],
                    details=f"no node class {node['class_type']!r} in /object_info",
                    expected=_suggest(node["class_type"], info) or None,
                )
            )
    outputs = sorted(
        (nid for nid, n in graph.items() if (info.get(n["class_type"]) or {}).get("output_node") is True),
        key=_node_order,
    )
    if not outputs and not errors:
        errors.append(
            Problem(
                "prompt_no_outputs",
                "Prompt has no outputs",
                details="nothing in the graph is an output node (one that saves or shows something, such as "
                "SaveImage or PreviewImage), so ComfyUI would run nothing",
            )
        )

    needed = _upstream(graph, outputs)
    for node_id in sorted(graph, key=_node_order):
        node = graph[node_id]
        if node["class_type"] not in info:
            continue  # its missing_node_type says it
        if node_id not in needed:
            if outputs:
                warnings.append(
                    Problem(
                        "not_connected_to_output",
                        "no output node depends on this node, so ComfyUI will not run it",
                        node_id=node_id,
                        class_type=node["class_type"],
                    )
                )
            continue
        for name, value in (node.get("inputs") or {}).items():
            if isinstance(value, list):  # ComfyUI takes every list for a link
                found = _check_link(name, value, graph, info)
                if found is not None:
                    kind, message, fields = found
                    errors.append(
                        Problem(kind, message, node_id=node_id, class_type=node["class_type"], input=name, **fields)
                    )

    return Report(
        errors[:MAX_PROBLEMS],
        warnings[:MAX_PROBLEMS],
        partner_api_nodes(graph, info),
        outputs,
        len(graph),
    )


def _upstream(graph: dict[str, Any], roots: list[str]) -> set[str]:
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        node_id = stack.pop()
        if node_id in seen or node_id not in graph:
            continue
        seen.add(node_id)
        for value in (graph[node_id].get("inputs") or {}).values():
            if _is_link(value):
                stack.append(value[0])
    return seen


def _check_link(
    name: str, value: list[Any], graph: dict[str, Any], info: dict[str, Any]
) -> tuple[str, str, dict[str, Any]] | None:
    """Whether a link points at a node and an output that exist; what it carries is ComfyUI's to judge."""
    if len(value) != 2:
        return (
            "bad_linked_input",
            "Bad linked input, must be a length-2 list of [node_id, slot_index]",
            {"details": name, "got": value},
        )
    source, slot = value
    if not isinstance(source, str) or not _is_link(value):
        return (
            "bad_linked_input",
            f'a link is ["<node id, a string>", <output index, a number>], such as ["{source}", 0]',
            {"details": name, "got": value},
        )
    if source not in graph:
        return (
            "linked_node_missing",
            f"input {name!r} links to node {source!r}, which is not in the workflow",
            {"got": value, "expected": _suggest(source, graph) or None},
        )
    source_spec = info.get(graph[source].get("class_type"))
    if source_spec is None:
        return None  # the source's own missing_node_type says it
    produced = source_spec.get("output") or []
    if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot < len(produced):
        return (
            "linked_output_missing",
            (
                f"node {source} ({graph[source]['class_type']}) has outputs 0 to {len(produced) - 1}, "
                f"and input {name!r} links to output {slot!r}"
            ),
            {"got": value, "expected": list(produced)},
        )
    return None
