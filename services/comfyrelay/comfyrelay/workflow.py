"""Check an API-format workflow against the live /object_info, without running it.

An API-format workflow maps node ids to `{"class_type": ..., "inputs": {...}}`.
An input's value is a constant, or a link `["<node id>", <output index>]`.

The checks follow what ComfyUI's own `/prompt` validation does at the pinned
version (`execution.py`: `validate_prompt` and `validate_inputs`), and a
problem ComfyUI also reports carries ComfyUI's `type` and message, so an agent
sees the same words either way:

    missing_node_type        the class is not installed (or a node has none)
    prompt_no_outputs        nothing in the graph is an output node
    required_input_missing   a required input has no value and no link
    bad_linked_input         a link is not a [node id, output index] pair
    return_type_mismatch     a link carries a type the input does not take
    invalid_input_type       a constant will not convert (INT, FLOAT)
    value_smaller_than_min   a number is under the input's min
    value_bigger_than_max    ... or over its max
    value_not_in_list        a COMBO value is not one of its options

Faults ComfyUI only trips over (an exception, not a clean error) get their
own types: `invalid_workflow` (not an API-format graph at all),
`linked_node_missing` and `linked_output_missing`.

Like ComfyUI, inputs are checked on the nodes an output node depends on; a
node nothing depends on does not run, so it gets a warning instead. Unlike
ComfyUI, one bad output fails the whole graph: ComfyUI would run the outputs
that pass and drop the rest. And a required DynamicCombo left out is
`required_input_missing` here, where ComfyUI's check lets it through and the
node then fails when it runs (checked at v0.37.0: ResizeImageMaskNode without
`resize_type` raises TypeError in execute).

What this cannot see: a node's own VALIDATE_INPUTS (so a file-picker COMBO
such as LoadImage's `image`, whose list is only what is on disk, gets a
warning, not an error, and ComfyUI's check at submission decides), and
anything that only fails while running.

Partner-API nodes are found here too (`partner_api_nodes`); the run tool
refuses a graph that has any.
"""

from __future__ import annotations

import difflib
from dataclasses import asdict, dataclass
from typing import Any

# ComfyUI's dynamic V3 inputs (comfy_api/latest/_io.py), which expand into
# more inputs according to the values the graph gives them.
AUTOGROW = "COMFY_AUTOGROW_V3"
DYNAMIC_COMBO = "COMFY_DYNAMICCOMBO_V3"
DYNAMIC_SLOT = "COMFY_DYNAMICSLOT_V3"
MATCH_TYPE = "COMFY_MATCHTYPE_V3"
ANY_TYPE = "*"

# The hidden inputs through which ComfyUI hands a node the user's Comfy.org
# credentials, which pay for partner-API calls.
COMFY_ORG_CREDENTIALS = frozenset({"AUTH_TOKEN_COMFY_ORG", "API_KEY_COMFY_ORG"})

# COMBO inputs whose options are files on disk. The node checks the value
# itself (VALIDATE_INPUTS), so a value outside the list is only a warning.
FILE_PICKER_KEYS = ("image_upload", "video_upload", "audio_upload", "upload", "remote")

MAX_PROBLEMS = 100
MAX_OPTIONS_SHOWN = 50


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
    return isinstance(value, list)


def _suggest(word: str, choices: Any, n: int = 3) -> list[str]:
    return difflib.get_close_matches(str(word), [str(c) for c in choices], n=n, cutoff=0.6)


def _type_name(input_type: Any) -> Any:
    """How to show an input type: a legacy COMBO is a list of options."""
    return "COMBO" if isinstance(input_type, list) else input_type


def types_compatible(received: Any, wanted: Any) -> bool:
    """ComfyUI's comfy_execution.validation.validate_node_input, non-strict."""
    if received == wanted:
        return True
    if ANY_TYPE in (received, wanted) or MATCH_TYPE in (received, wanted):
        return True
    if isinstance(received, list) and wanted == "COMBO":
        return True
    if not isinstance(received, str) or not isinstance(wanted, str):
        return False
    got = {t.strip() for t in received.split(",")}
    want = {t.strip() for t in wanted.split(",")}
    return ANY_TYPE in got or ANY_TYPE in want or bool(got & want)


# -- the input spec, expanded against the graph's values ----------------------


def expand_inputs(spec: dict[str, Any], live: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The node's required and optional inputs, with dynamic ones expanded against `live` (the graph's values).

    A port of ComfyUI's get_finalized_class_inputs: an Autogrow input becomes
    `<id>.<prefix><n>` inputs, and a DynamicCombo adds the inputs of the
    option it is set to, as `<id>.<name>`. A DynamicCombo itself is checked as
    an ordinary COMBO of its option keys.
    """
    out: dict[str, dict[str, Any]] = {"required": {}, "optional": {}}
    _parse(out, live, {k: spec.get(k) for k in ("required", "optional")}, [])
    return out


def _parse(out: dict[str, dict[str, Any]], live: dict[str, Any], section: dict[str, Any], prefix: list[str]) -> None:
    for category, inputs in section.items():
        if category not in out or not isinstance(inputs, dict):
            continue
        for name, value in inputs.items():
            io_type = value[0] if isinstance(value, list) and value else None
            path = [*prefix, name]
            extra = value[1] if isinstance(value, list) and len(value) > 1 and isinstance(value[1], dict) else {}
            if io_type == AUTOGROW:
                _autogrow(out, extra, path)
            elif io_type == DYNAMIC_COMBO:
                _dynamic_combo(out, live, extra, category, path)
            elif io_type == DYNAMIC_SLOT:
                if ".".join(path) in live:
                    _parse(out, live, extra.get("inputs") or {}, path)
                    out[category][".".join(path)] = [extra.get("slotType", ANY_TYPE), extra]
            else:
                out[category][".".join(path)] = value


def _autogrow(out: dict[str, dict[str, Any]], extra: dict[str, Any], path: list[str]) -> None:
    template = extra.get("template") or {}
    if "names" in template:
        names = list(template["names"])
    else:
        names = [f"{template.get('prefix', '')}{i}" for i in range(int(template.get("max", 0)))]
    minimum = int(template.get("min", 1))
    template_input, template_required = None, True
    for category, inputs in (template.get("input") or {}).items():
        if inputs:
            template_input = next(iter(inputs.values()))
            template_required = category == "required"
            break
    if template_input is None:
        return
    for i, name in enumerate(names):
        category = "required" if i < minimum and template_required else "optional"
        out[category][".".join([*path, name])] = template_input


def _dynamic_combo(
    out: dict[str, dict[str, Any]],
    live: dict[str, Any],
    extra: dict[str, Any],
    category: str,
    path: list[str],
) -> None:
    key = ".".join(path)
    options = [o for o in extra.get("options") or [] if isinstance(o, dict)]
    out[category][key] = ["COMBO", {"options": [o.get("key") for o in options]}]
    if key in live:
        for option in options:
            if option.get("key") == live[key]:
                _parse(out, live, option.get("inputs") or {}, path)
                break


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
    """Nodes that call a paid partner API, as /object_info marks them.

    Two signals: `api_node: true` (ComfyUI sets it from a node's API_NODE
    flag; it is what --disable-api-nodes and the editor's badge go by), and
    asking for the user's Comfy.org credentials through a hidden input, which
    is how such a node pays. Either one is enough.
    """
    found = []
    for node_id, node in graph.items():
        spec = info.get(node.get("class_type")) if isinstance(node, dict) else None
        if not isinstance(spec, dict):
            continue
        signals = []
        if spec.get("api_node") is True:
            signals.append("api_node")
        hidden = (spec.get("input") or {}).get("hidden") or {}
        hidden_types = {v[0] if isinstance(v, list) and v else v for v in hidden.values()}
        if hidden_types & COMFY_ORG_CREDENTIALS:
            signals.append("comfy_org_credentials")
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
    """Every problem in `graph` that /object_info (`info`) can show, without running it."""
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
        spec = info.get(node["class_type"])
        if spec is None:
            continue
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
        _check_node(node_id, node, spec, graph, info, errors, warnings)

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
            if _is_link(value) and len(value) == 2 and isinstance(value[0], str):
                stack.append(value[0])
    return seen


def _check_node(
    node_id: str,
    node: dict[str, Any],
    spec: dict[str, Any],
    graph: dict[str, Any],
    info: dict[str, Any],
    errors: list[Problem],
    warnings: list[Problem],
) -> None:
    class_type = node["class_type"]
    inputs = node.get("inputs") or {}
    expanded = expand_inputs(spec.get("input") or {}, inputs)
    known = {**expanded["optional"], **expanded["required"]}

    def problem(kind: str, message: str, name: str | None, **kw: Any) -> Problem:
        return Problem(kind, message, node_id=node_id, class_type=class_type, input=name, **kw)

    for name in expanded["required"]:
        if name not in inputs:
            errors.append(
                problem(
                    "required_input_missing",
                    "Required input is missing",
                    name,
                    details=name,
                    expected=_type_name(expanded["required"][name][0]),
                )
            )

    hidden = (spec.get("input") or {}).get("hidden") or {}
    for name in sorted(set(inputs) - set(known) - set(hidden)):
        warnings.append(
            problem(
                "unknown_input",
                f"{class_type} has no input {name!r}; ComfyUI ignores it",
                name,
                expected=_suggest(name, known) or None,
            )
        )

    for name, input_spec in known.items():
        if name not in inputs:
            continue
        value = inputs[name]
        input_type = input_spec[0] if isinstance(input_spec, list) and input_spec else None
        extra = input_spec[1] if isinstance(input_spec, list) and len(input_spec) > 1 else {}
        extra = extra if isinstance(extra, dict) else {}
        if _is_link(value):
            found = _check_link(name, value, input_type, graph, info)
            if found is not None:
                errors.append(problem(*found[:2], name, **found[2]))
            continue
        for kind, message, level, kw in _check_constant(name, value, input_type, extra):
            (errors if level == "error" else warnings).append(problem(kind, message, name, **kw))


def _check_link(
    name: str, value: list[Any], input_type: Any, graph: dict[str, Any], info: dict[str, Any]
) -> tuple[str, str, dict[str, Any]] | None:
    if len(value) != 2:
        return (
            "bad_linked_input",
            "Bad linked input, must be a length-2 list of [node_id, slot_index]",
            {"details": name, "got": value},
        )
    source, slot = value
    if not isinstance(source, str):
        return (
            "bad_linked_input",
            f'a link names its node by id as a string, such as ["{source}", {slot}]',
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
    received = produced[slot]
    if not types_compatible(received, input_type):
        return (
            "return_type_mismatch",
            "Return type mismatch between linked nodes",
            {
                "details": f"{name}, received_type({received}) mismatch input_type({_type_name(input_type)})",
                "expected": _type_name(input_type),
                "got": received,
            },
        )
    return None


def _check_constant(
    name: str, value: Any, input_type: Any, extra: dict[str, Any]
) -> list[tuple[str, str, str, dict[str, Any]]]:
    """(type, message, "error" or "warning", fields) for each problem with a constant value."""
    if isinstance(value, dict) and "__value__" in value:
        value = value["__value__"]
    convert = {"INT": int, "FLOAT": float}.get(input_type) if isinstance(input_type, str) else None
    if convert is not None:
        try:
            value = convert(value)
        except (TypeError, ValueError, OverflowError) as exc:
            return [
                (
                    "invalid_input_type",
                    f"Failed to convert an input value to a {input_type} value",
                    "error",
                    {"details": f"{name}, {value}, {exc}", "expected": input_type, "got": value},
                )
            ]
        if "min" in extra and isinstance(extra["min"], (int, float)) and value < extra["min"]:
            return [
                (
                    "value_smaller_than_min",
                    f"Value {value} smaller than min of {extra['min']}",
                    "error",
                    {"details": name, "expected": {"min": extra["min"]}, "got": value},
                )
            ]
        if "max" in extra and isinstance(extra["max"], (int, float)) and value > extra["max"]:
            return [
                (
                    "value_bigger_than_max",
                    f"Value {value} bigger than max of {extra['max']}",
                    "error",
                    {"details": name, "expected": {"max": extra["max"]}, "got": value},
                )
            ]
        return []
    if isinstance(input_type, list) or input_type == "COMBO":
        options = input_type if isinstance(input_type, list) else extra.get("options") or []
        values = value if extra.get("multiselect") and isinstance(value, list) else [value]
        bad = [v for v in values if v not in options]
        if not bad:
            return []
        file_picker = any(k in extra for k in FILE_PICKER_KEYS)
        shown = options[:MAX_OPTIONS_SHOWN]
        fields = {
            "details": f"{name}: {', '.join(repr(v) for v in bad)} not in "
            + (str(shown) if len(options) <= MAX_OPTIONS_SHOWN else f"(list of length {len(options)})"),
            "expected": shown,
            "got": value,
        }
        close = _suggest(bad[0], options)
        if close:
            fields["details"] += f"; did you mean {', '.join(repr(c) for c in close)}?"
        if file_picker:
            return [
                (
                    "value_not_in_list",
                    (
                        "Value not in list: this input picks a file, and the file is not among those ComfyUI "
                        "lists. ComfyUI checks the file itself when the workflow is submitted"
                    ),
                    "warning",
                    fields,
                )
            ]
        return [("value_not_in_list", "Value not in list", "error", fields)]
    if isinstance(input_type, str) and input_type not in ("STRING", "BOOLEAN") and _is_socket_type(input_type):
        return [
            (
                "constant_for_link",
                f"input {name!r} takes a {input_type} from another node's output, and got a constant",
                "warning",
                {"expected": input_type, "got": value},
            )
        ]
    return []


def _is_socket_type(input_type: str) -> bool:
    """A type that only a link supplies: IMAGE, MODEL, LATENT and the like, not a widget's value."""
    return (
        input_type.isupper()
        and not input_type.startswith("COMFY_")
        and input_type not in ("INT", "FLOAT", "STRING", "BOOLEAN", "COMBO")
    )
