"""The `read` profile's introspection tools (#133): nodes, models and templates.

Every answer comes from the live ComfyUI this relay serves, through
`ComfyUIClient`, so it matches what that instance will actually accept:

    node_search      /object_info, ranked for a query
    node_describe    /object_info/<class>, rendered as a full input/output spec,
                     with the node's help page (/docs/<class>/en.md, or the
                     pack's own under /extensions/<pack>/docs/) when it has one
    model_list       /models and /models/<folder>
    template_search  /templates/index.json, enriched from index.mcp.json when
                     ComfyUI serves it, plus a runnability check per match
                     (from requirements cached per templates version), with
                     a compact summary of it per hit
    template_get     /templates/<name>.json, plus the same check

All of them are read-only (#103: no writes, no installs, and no calls to
anything but the configured ComfyUI). Templates are not bundled here: ComfyUI
serves the comfyui-workflow-templates package it pins, and the relay reads it
from there.

The runnability check follows comfy-mcp's `local_check` pattern. For a
template's active nodes (bypassed or muted ones don't run, and notes, reroutes
and primitives exist only in the frontend) it asks: is every class in
/object_info, does any of them spend partner-API credits, is every model the
template declares (`properties.models` on its nodes) on disk under the name
the template uses, and is every file its core loaders name in ComfyUI's input
directory? Nested subgraphs are followed. It does not validate the graph.

`tools.py` wraps each entry of INTROSPECTION_TOOLS in its ToolSpec.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import math
import re
from collections import Counter, OrderedDict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import quote

from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field, model_serializer

from .comfyui import ComfyUIClient, ComfyUIError
from .errors import RelayError
from .workflow import (
    AUTOGROW,
    DYNAMIC_COMBO,
    DYNAMIC_SLOT,
    MATCH_TYPE,
    autogrow_item,
    autogrow_min,
    autogrow_names,
    partner_signals,
    qualified,
)

if TYPE_CHECKING:
    from .tools import Relay

log = logging.getLogger("comfyrelay")

READ = frozenset({"read"})
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

# Node types a template may hold that ComfyUI never executes: the frontend
# draws them (notes), folds them away (reroutes) or turns them into widget
# values (primitives) before a graph is sent.
FRONTEND_ONLY = frozenset({"Note", "MarkdownNote", "Reroute", "PrimitiveNode"})
# LiteGraph node modes that keep a node out of the run: 2 muted, 4 bypassed.
INACTIVE_MODES = frozenset({2, 4})
# Not model folders, though /models lists them. custom_nodes would list node
# packs' source files. download_model_base is a key in extra_model_paths.yaml
# (this repo's examples set it) that ComfyUI registers as a folder type: it
# names the whole models root, so it would list every model a second time.
NOT_MODEL_FOLDERS = frozenset({"custom_nodes", "download_model_base"})
FETCH_CONCURRENCY = 8
# A node's help page is read up to this many bytes. The longest in comfyui-embedded-docs 0.5.12 is about 11 KB.
HELP_MAX_BYTES = 64 * 1024
# Never sent as a path segment: /object_info/.. or /models/. would be
# normalised to another route.
DOT_SEGMENTS = frozenset({".", ".."})

TEMPLATES_SOURCE = {
    "package": "comfyui-workflow-templates",
    "license": "MIT",
    "url": "https://github.com/Comfy-Org/workflow_templates",
    "notice": "Templates are Comfy Org's, under the MIT license. comfyrelay is not affiliated with or "
    "endorsed by Comfy Org.",
}

_STOPWORDS = frozenset({"a", "an", "and", "the", "of", "for", "to", "with", "in", "on", "my", "node", "nodes"})


class _Compact(BaseModel):
    """Leaves out fields that are None, so a spec lists only what a node declares."""

    @model_serializer(mode="wrap")
    def _drop_none(self, handler: Callable[[Any], dict[str, Any]]) -> dict[str, Any]:
        return {k: v for k, v in handler(self).items() if v is not None}


def _words(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+(?:\.[a-z0-9]+)*", text.lower())  # keeps "sd1.5" and "2.1" whole
    return [w for w in words if w not in _STOPWORDS] or words


def _squash(text: str) -> str:
    """Lowercase letters and digits only: "Empty Latent Image" and "EmptyLatentImage" squash alike."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _one_line(text: Any, limit: int = 160) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return None
    line = text.strip().splitlines()[0].strip()
    sentence = re.split(r"(?<=[.!?])\s", line, maxsplit=1)[0]
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rstrip() + "…"


def _bad(what: str) -> ComfyUIError:
    return ComfyUIError("comfyui_bad_response", f"ComfyUI answered with {what}")


def _pack(info: dict[str, Any]) -> str | None:
    """The custom node pack a class comes from; None for ComfyUI's own nodes (including its partner-API nodes)."""
    module = str(info.get("python_module") or "")
    parts = module.split(".")
    return parts[1] if parts[0] == "custom_nodes" and len(parts) > 1 else None


def _checked_object_info(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not all(isinstance(v, dict) for v in data.values()):
        raise _bad("an /object_info whose entries are not all objects")
    return data


# -- node_search --------------------------------------------------------------

MatchKind = Literal["exact", "prefix", "name", "category", "description"]
_TIERS: tuple[MatchKind, ...] = ("exact", "prefix", "name", "category", "description")


class NodeHit(_Compact):
    class_type: str = Field(description="The class to put in a workflow's class_type, exactly as written")
    display_name: str
    category: str
    summary: str | None = Field(default=None, description="The first sentence of the node's description")
    pack: str | None = Field(default=None, description="The custom node pack it comes from; absent for built-ins")
    match: MatchKind = Field(description="What matched, best first: exact, prefix, name, category, description")
    api_node: bool | None = Field(default=None, description="true: a partner-API node, which spends credits")
    deprecated: bool | None = None


class NodeSearchResult(BaseModel):
    query: str
    total_matches: int
    node_count: int = Field(description="How many node classes the instance has")
    results: list[NodeHit]


def _invalid_query(query: str) -> RelayError:
    return RelayError("invalid_query", f"{query!r} has no letters or digits to search for")


def _match_tier(query: str, words: list[str], class_type: str, info: dict[str, Any]) -> int | None:
    display = str(info.get("display_name") or class_type)
    squashed = _squash(query)
    names = (_squash(class_type), _squash(display))
    if squashed and squashed in names:
        return 0
    if squashed and any(n.startswith(squashed) for n in names):
        return 1
    aliases = info.get("search_aliases") if isinstance(info.get("search_aliases"), list) else []
    blob = " ".join([class_type, display, *map(str, aliases)]).lower()
    for tier, extra in ((2, ""), (3, str(info.get("category") or "")), (4, str(info.get("description") or ""))):
        blob = f"{blob} {extra.lower()}"
        if all(w in blob for w in words):
            return tier
    return None


def _node_search(relay: Relay) -> Callable[..., Any]:
    async def node_search(
        query: str = Field(min_length=1, description="Words or a class name: 'load checkpoint', 'KSampler', 'upscale'"),
        limit: int = Field(default=20, ge=1, le=100),
    ) -> NodeSearchResult:
        """Find node classes in the live ComfyUI (built-in and custom nodes) by class name, display name, alias,
        category or description.

        Use it to find the right node, then node_describe for its inputs, defaults, limits and outputs. Each hit
        gives the class_type to use in a workflow. Exact and prefix matches on the name rank first, so near
        namesakes stay apart: CheckpointLoaderSimple ("Load Checkpoint") is not CheckpointLoader (deprecated).
        Partner-API nodes (api_node, they spend credits) and deprecated ones rank after the rest of their tier.
        """
        words = _words(query)
        if not words:
            raise _invalid_query(query)
        info = _checked_object_info(await relay.comfyui.object_info())
        ranked = []
        for class_type, node in info.items():
            tier = _match_tier(query, words, class_type, node)
            if tier is not None:
                key = (tier, bool(node.get("deprecated")), bool(partner_signals(node)), len(class_type), class_type)
                ranked.append((key, class_type, node))
        ranked.sort(key=lambda r: r[0])
        return NodeSearchResult(
            query=query,
            total_matches=len(ranked),
            node_count=len(info),
            results=[
                NodeHit(
                    class_type=class_type,
                    display_name=str(node.get("display_name") or class_type),
                    category=str(node.get("category") or ""),
                    summary=_one_line(node.get("description")),
                    pack=_pack(node),
                    match=_TIERS[key[0]],
                    api_node=True if partner_signals(node) else None,
                    deprecated=True if node.get("deprecated") else None,
                )
                for key, class_type, node in ranked[:limit]
            ],
        )

    return node_search


# -- node_describe ------------------------------------------------------------

# ComfyUI's dynamic V3 inputs, and how the inputs inside one are named
# (`resize_type.width`, `images.image0`), come from workflow.py, which
# workflow_validate checks graphs with: one naming rule for both.
# Keys rendered as fields of their own, not repeated under `other`.
_SPEC_KEYS = frozenset({"default", "min", "max", "step", "tooltip", "options"})
_DYNAMIC_KEYS = frozenset({"template", "inputs", "slotType"})
DEFAULT_MAX_OPTIONS = 20


class AutogrowSpec(_Compact):
    names: list[str] = Field(description="The inputs it can take, fully qualified and in order (first max_options)")
    names_total: int
    names_truncated: bool | None = None
    prefix: str | None = Field(
        default=None, description="Fully qualified: the inputs are this plus 0, 1, 2 ... up to max - 1"
    )
    min: int = Field(description="The first `min` names are required when the item is; the rest are optional")
    max: int
    item: InputSpec = Field(description="What each of those inputs takes")


class MatchTypeSpec(_Compact):
    template_id: str = Field(description="Outputs whose same_type_as names this input carry the type connected here")
    allowed_types: list[str] = Field(description="The types this input accepts")


class InputSpec(_Compact):
    name: str = Field(
        description="The key in a graph node's inputs. Inside a dynamic input it is fully qualified with dots: "
        "resize_type.width, images.image0"
    )
    type: str = Field(
        description="COMBO for a choice from `options`; COMFY_DYNAMICCOMBO_V3 for a choice whose option adds "
        "inputs; COMFY_AUTOGROW_V3 for a growing list of inputs (see autogrow); COMFY_MATCHTYPE_V3 for an input "
        "that takes any of match_type.allowed_types; otherwise a type such as INT, IMAGE, MODEL"
    )
    required: bool
    default: Any = None
    min: int | float | None = None
    max: int | float | None = None
    step: int | float | None = None
    options: list[Any] | None = Field(
        default=None,
        description="COMBO values (first max_options). For a COMFY_DYNAMICCOMBO_V3, each is {value, inputs}: set "
        "this input to `value`, and give the graph that option's inputs, under their qualified names",
    )
    options_total: int | None = Field(default=None, description="How many values there are in all")
    options_truncated: bool | None = None
    autogrow: AutogrowSpec | None = None
    match_type: MatchTypeSpec | None = None
    slot_inputs: list[InputSpec] | None = Field(
        default=None, description="COMFY_DYNAMICSLOT_V3: the inputs it adds when something is connected to it"
    )
    tooltip: str | None = None
    other: dict[str, Any] | None = Field(default=None, description="Any further flags the node declares")


class OutputSpec(_Compact):
    index: int = Field(description="The output socket, as a link [node_id, index] refers to it")
    type: str = Field(description="COMFY_MATCHTYPE_V3: the same type as the input named in same_type_as")
    name: str
    is_list: bool
    same_type_as: str | None = Field(
        default=None, description="For a COMFY_MATCHTYPE_V3 output: the input whose connected type it carries"
    )
    tooltip: str | None = None


class NodeSpec(_Compact):
    class_type: str
    display_name: str
    category: str
    description: str | None = None
    pack: str | None = Field(default=None, description="The custom node pack it comes from; absent for built-ins")
    python_module: str | None = None
    output_node: bool = Field(description="true: a graph can end here (it saves, previews or returns a value)")
    api_node: bool = Field(description="true: a partner-API node, which spends credits")
    deprecated: bool | None = None
    experimental: bool | None = None
    inputs: list[InputSpec] = Field(description="Required inputs first, then optional ones, in the node's order")
    hidden_inputs: list[str] | None = Field(default=None, description="Filled in by ComfyUI, never by a workflow")
    outputs: list[OutputSpec]
    help: str | None = Field(
        default=None,
        description="The node's help page (English markdown), as ComfyUI serves it to the editor; absent when it "
        "has none",
    )
    help_path: str | None = Field(default=None, description="Where on ComfyUI the help page came from")
    help_truncated: bool | None = Field(
        default=None, description=f"true: the help page is longer than {HELP_MAX_BYTES} bytes, and help is its start"
    )


AutogrowSpec.model_rebuild()


def _help_paths(class_type: str, info: dict[str, Any]) -> list[str]:
    """Where ComfyUI serves a node's English help, in the order the editor tries them (ComfyUI frontend 1.52,
    NodeHelpService): a custom node's pack serves its own under /extensions/<pack>/docs/, per locale and then
    locale-free; ComfyUI's own nodes' come from comfyui-embedded-docs at /docs/<class>/<locale>.md."""
    name = quote(class_type, safe="")
    module = str(info.get("python_module") or "").split(".")
    if module[0] == "custom_nodes":
        if len(module) < 2 or not module[1]:
            return []
        pack = quote(module[1].split("@")[0], safe="")
        return [f"/extensions/{pack}/docs/{name}/en.md", f"/extensions/{pack}/docs/{name}.md"]
    return [f"/docs/{name}/en.md"]


async def _help(comfyui: ComfyUIClient, class_type: str, info: dict[str, Any]) -> tuple[str, str, bool] | None:
    """The first help page ComfyUI has for the node: (text, path, truncated). A page it can't serve, for whatever
    reason, is no help page, as in the editor (tryFetchMarkdown): it never fails node_describe."""
    for path in _help_paths(class_type, info):
        try:
            found = await comfyui.markdown(path, HELP_MAX_BYTES)
        except ComfyUIError:
            continue
        if found is not None:
            return found[0], path, found[1]
    return None


def _number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _cut(values: list[Any], limit: int) -> tuple[list[Any], int, bool | None]:
    return values[:limit], len(values), True if len(values) > limit else None


def _autogrow(qname: str, template: dict[str, Any], required: bool, max_options: int) -> AutogrowSpec | None:
    """ComfyUI's Autogrow._expand_schema_for_dynamic, as a naming rule: `<qname>.<name>` for each name."""
    prefix = template.get("prefix") if isinstance(template.get("prefix"), str) else None
    names, each = autogrow_names(template), autogrow_item(template)
    if names is None or each is None:
        return None
    label = f"{qname}.{prefix}<n>" if prefix is not None else f"{qname}.<name>"
    item = _input([], label, each[0], required and each[1], max_options)
    shown, total, truncated = _cut([qualified([qname, n]) for n in names], max_options)
    minimum = autogrow_min(template)
    return AutogrowSpec(
        names=shown,
        names_total=total,
        names_truncated=truncated,
        prefix=f"{qname}.{prefix}" if prefix is not None else None,
        min=minimum,
        max=len(names),
        item=item,
    )


def _option(value: Any, path: list[str], max_options: int) -> Any:
    """A COMBO value. A DynamicCombo's is {"key", "inputs"}: its inputs are named under the combo's path."""
    if isinstance(value, dict) and "key" in value:
        nested = value.get("inputs") if isinstance(value.get("inputs"), dict) else {}
        return {"value": value["key"], "inputs": [i.model_dump() for i in _inputs(nested, max_options, path=path)]}
    return value


def _input(path: list[str], name: str, spec: Any, required: bool, max_options: int) -> InputSpec:
    qname = qualified([*path, name])
    if isinstance(spec, str):
        spec = [spec]
    if not isinstance(spec, list) or not spec:
        return InputSpec(name=qname, type="UNKNOWN", required=required)
    kind = spec[0]
    opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    dynamic = kind in (AUTOGROW, DYNAMIC_COMBO, DYNAMIC_SLOT, MATCH_TYPE)
    options = kind if isinstance(kind, list) else opts.get("options")
    options = options if isinstance(options, list) else None
    shown, total, truncated = _cut(options, max_options) if options is not None else (None, None, None)
    template = opts.get("template") if isinstance(opts.get("template"), dict) else {}
    other = {k: v for k, v in opts.items() if k not in _SPEC_KEYS and not (dynamic and k in _DYNAMIC_KEYS)}
    match_type = None
    if kind == MATCH_TYPE and isinstance(template.get("template_id"), str):
        allowed = str(template.get("allowed_types") or "*")
        match_type = MatchTypeSpec(template_id=template["template_id"], allowed_types=allowed.split(","))
    slot = opts.get("inputs") if kind == DYNAMIC_SLOT and isinstance(opts.get("inputs"), dict) else None
    if kind == DYNAMIC_SLOT:
        kind = str(opts.get("slotType") or kind)
    return InputSpec(
        name=qname,
        type="COMBO" if isinstance(kind, list) else str(kind),
        required=required,
        default=opts.get("default"),
        min=_number(opts.get("min")),
        max=_number(opts.get("max")),
        step=_number(opts.get("step")),
        options=None if shown is None else [_option(o, [*path, name], max_options) for o in shown],
        options_total=total,
        options_truncated=truncated,
        autogrow=_autogrow(qname, template, required, max_options) if kind == AUTOGROW else None,
        match_type=match_type,
        slot_inputs=None if slot is None else _inputs(slot, max_options, path=[*path, name]),
        tooltip=opts.get("tooltip") if isinstance(opts.get("tooltip"), str) else None,
        other=other or None,
    )


def _inputs(
    sections: dict[str, Any], max_options: int, order: dict[str, Any] | None = None, path: list[str] | None = None
) -> list[InputSpec]:
    out = []
    for section in ("required", "optional"):
        specs = sections.get(section)
        if not isinstance(specs, dict):
            continue
        names = (order or {}).get(section)
        names = names if isinstance(names, list) and set(names) == set(specs) else list(specs)
        out += [_input(path or [], name, specs[name], section == "required", max_options) for name in names]
    return out


def _outputs(info: dict[str, Any], inputs: list[InputSpec]) -> list[OutputSpec]:
    types = info.get("output") if isinstance(info.get("output"), list) else []
    by_template = {i.match_type.template_id: i.name for i in inputs if i.match_type is not None}

    def at(key: str, i: int, fallback: Any) -> Any:
        values = info.get(key)
        return values[i] if isinstance(values, list) and i < len(values) else fallback

    return [
        OutputSpec(
            index=i,
            type="COMBO" if isinstance(t, list) else str(t),
            name=str(at("output_name", i, t if isinstance(t, str) else "COMBO")),
            is_list=bool(at("output_is_list", i, False)),
            same_type_as=by_template.get(at("output_matchtypes", i, None)) if t == MATCH_TYPE else None,
            tooltip=at("output_tooltips", i, None) if isinstance(at("output_tooltips", i, None), str) else None,
        )
        for i, t in enumerate(types)
    ]


def _spec(class_type: str, info: dict[str, Any], max_options: int) -> NodeSpec:
    sections = info.get("input")
    if not isinstance(sections, dict):
        raise _bad(f'an /object_info/{class_type} with no "input" object')
    hidden = sections.get("hidden")
    inputs = _inputs(
        sections, max_options, info.get("input_order") if isinstance(info.get("input_order"), dict) else None
    )
    return NodeSpec(
        class_type=class_type,
        display_name=str(info.get("display_name") or class_type),
        category=str(info.get("category") or ""),
        description=info.get("description") or None,
        pack=_pack(info),
        python_module=info.get("python_module"),
        output_node=bool(info.get("output_node")),
        api_node=bool(partner_signals(info)),
        deprecated=True if info.get("deprecated") else None,
        experimental=True if info.get("experimental") else None,
        inputs=inputs,
        hidden_inputs=list(hidden) if isinstance(hidden, dict) and hidden else None,
        outputs=_outputs(info, inputs),
    )


def _close_matches(query: str, names: Iterable[tuple[str, str]], n: int = 5) -> list[dict[str, str]]:
    """Node classes or templates whose id or display name is close to `query`: case-insensitive, squashed, fuzzy."""
    by_key: dict[str, list[tuple[str, str]]] = {}
    for ident, display in names:
        for key in {ident.lower(), _squash(ident), display.lower(), _squash(display)}:
            by_key.setdefault(key, []).append((ident, display))
    keys = difflib.get_close_matches(query.lower(), by_key, n=n * 3, cutoff=0.6)
    keys += difflib.get_close_matches(_squash(query), by_key, n=n * 3, cutoff=0.6)
    keys += [k for k in by_key if len(_squash(query)) >= 3 and _squash(query) in k]
    seen: dict[str, str] = {}
    for key in keys:
        for ident, display in by_key[key]:
            seen.setdefault(ident, display)
    return [{"id": ident, "display_name": display} for ident, display in list(seen.items())[:n]]


def _node_describe(relay: Relay) -> Callable[..., Any]:
    async def node_describe(
        class_type: str = Field(min_length=1, description="The exact class, as node_search returns it: 'KSampler'"),
        max_options: int = Field(
            default=DEFAULT_MAX_OPTIONS,
            ge=1,
            le=5000,
            description="Show at most this many values of each COMBO input and names of each Autogrow input. It "
            "applies at every level, so a dynamic combo's options each list their own inputs within it",
        ),
    ) -> NodeSpec:
        """Get one node class's full spec from the live ComfyUI: every input with its type, default, min, max and
        step, and a COMBO input's allowed values; its outputs in socket order with their names; whether it is an
        output node; and whether it is a partner-API node.

        Look defaults and limits up here rather than recalling them: they change between ComfyUI versions. Use
        each input's `name` as the key in a graph: inputs added by a dynamic input are fully qualified with dots
        (a COMFY_DYNAMICCOMBO_V3 `resize_type` set to an option adds `resize_type.width`; a COMFY_AUTOGROW_V3
        `images` takes `images.image0`, `images.image1`, ...). Long lists are cut to max_options, with a total.
        `help` is the node's help page, the markdown the editor shows for it, when ComfyUI has one.
        An unknown class fails with `unknown_node_class` and a `suggestions` list of close class names.
        """
        found = {} if class_type in DOT_SEGMENTS else await relay.comfyui.object_info(class_type)
        if class_type in found:
            if not isinstance(found[class_type], dict):
                raise _bad(f"an /object_info/{class_type} that is not an object")
            spec = _spec(class_type, found[class_type], max_options)
            page = await _help(relay.comfyui, class_type, found[class_type])
            if page:
                spec.help, spec.help_path, spec.help_truncated = page[0], page[1], page[2] or None
            return spec
        if found:
            raise _bad(f"an /object_info/{class_type} that describes other classes")
        every = _checked_object_info(await relay.comfyui.object_info())
        suggestions = _close_matches(class_type, ((k, str(v.get("display_name") or k)) for k, v in every.items()))
        raise RelayError(
            "unknown_node_class",
            f"ComfyUI has no node class {class_type!r}. Class names are case-sensitive; "
            + ("close matches are in suggestions." if suggestions else "find one with node_search."),
            suggestions=[{"class_type": s["id"], "display_name": s["display_name"]} for s in suggestions],
        )

    return node_describe


# -- model_list ---------------------------------------------------------------


DEFAULT_MAX_FILES = 50
MAX_TOTAL_FILES = 400


class ModelFolder(BaseModel):
    folder: str = Field(description="The folder type, as a template's model `directory` names it")
    count: int
    files: list[str] = Field(description="Paths as loader nodes list them, relative to the folder")
    truncated: bool


class ModelListResult(BaseModel):
    folders: list[ModelFolder] = Field(description="Folders with at least one file")
    empty_folders: list[str] = Field(description="Folder types ComfyUI knows that hold nothing yet")


async def _gather_limited(calls: Iterable[Callable[[], Any]]) -> list[Any]:
    gate = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def one(call: Callable[[], Any]) -> Any:
        async with gate:
            return await call()

    return await asyncio.gather(*(one(c) for c in calls))


def _model_list(relay: Relay) -> Callable[..., Any]:
    async def model_list(
        folder: str | None = Field(
            default=None, description="One folder type, such as 'checkpoints' or 'loras'; omit for every folder"
        ),
        max_files: int = Field(
            default=DEFAULT_MAX_FILES,
            ge=1,
            le=10000,
            description=f"Per folder. Across all folders at most {MAX_TOTAL_FILES} are listed; `count` is always "
            "the full number",
        ),
    ) -> ModelListResult:
        """List the model files actually on disk in the live ComfyUI, by folder type (checkpoints, loras, vae,
        text_encoders, diffusion_models, ...), as its loader nodes offer them.

        Use it to see what a workflow can load. It only reads: nothing is downloaded or installed here. Lists are
        cut to max_files per folder (truncated says so); ask for one folder to see more of it. An unknown folder
        fails with `unknown_model_folder` and the folder types ComfyUI knows.
        """
        known = [f for f in await relay.comfyui.model_folders() if f not in NOT_MODEL_FOLDERS | DOT_SEGMENTS]
        if folder is not None and folder not in known:
            raise RelayError(
                "unknown_model_folder",
                f"ComfyUI has no model folder type {folder!r}",
                folders=known,
            )
        wanted = [folder] if folder is not None else known
        listings = await _gather_limited(lambda f=f: relay.comfyui.model_files(f) for f in wanted)
        folders, budget = [], MAX_TOTAL_FILES
        for f, files in zip(wanted, listings, strict=True):
            if files or folder is not None:
                shown = files[: min(max_files, budget)]
                budget -= len(shown)
                folders.append(ModelFolder(folder=f, count=len(files), files=shown, truncated=len(shown) < len(files)))
        return ModelListResult(
            folders=folders, empty_folders=[f for f, files in zip(wanted, listings) if not files and folder is None]
        )

    return model_list


# -- templates ----------------------------------------------------------------


class MissingNode(BaseModel):
    class_type: str
    pack: str | None = Field(description="The node pack the template names for it (cnr_id), when it names one")
    count: int


class MissingModel(BaseModel):
    name: str
    directory: str = Field(description="The model folder type it belongs in")
    url: str | None = Field(
        description="Where the template says it comes from. Nothing here downloads it: to add it, propose an entry "
        "in the deployment's manifest (comfy.yaml) for a human to apply"
    )
    folder_known: bool = Field(description="false: this ComfyUI has no such folder type at all")


class MisplacedModel(BaseModel):
    name: str = Field(description="The file name the template's loader asks for")
    directory: str
    found_at: str = Field(description="Where it is on disk, relative to the folder: the value the loader needs")
    needs_value_change: str = Field(
        description="What to change: ComfyUI rejects the template's bare name (value_not_in_list)"
    )


class MissingInput(BaseModel):
    class_type: str = Field(description="The loader node, such as LoadImage")
    input: str
    file: str = Field(description="The file it names, which is not in ComfyUI's input directory")


class Runnability(BaseModel):
    runnable: bool = Field(
        description="true only when every check here passed: every node class is present, every declared model is "
        "on disk under the name the template uses, every file its LoadImage, LoadImageMask, LoadAudio and "
        "LoadVideo nodes name is in the input directory, and no partner-API node is used. It does not validate "
        "the graph (links, types, values), models named only in widget values, other nodes' files, or whether "
        "the machine has the memory for it"
    )
    missing_nodes: list[MissingNode]
    missing_models: list[MissingModel]
    models_need_value_change: list[MisplacedModel] = Field(
        description="Declared models that are on disk only in a subfolder, so the loader's value must change"
    )
    missing_inputs: list[MissingInput] = Field(
        description="Input files the template's loaders name that ComfyUI's input directory lacks. Template "
        "example inputs are not served with the templates; upload the file or pick another"
    )
    api_nodes: list[str] = Field(
        description="Partner-API node classes it uses. They spend credits, and comfyrelay refuses to run them."
    )
    node_classes_checked: int
    models_checked: int = Field(description="Models the template declares on its nodes; only these are checked")


# What a search hit keeps of a runnability check: a count per kind and its first few names, each cut.
HIT_NAMES_MAX, HIT_NAME_MAX_CHARS = 3, 80


class Missing(BaseModel):
    count: int
    first: list[str] = Field(
        description=f"The first {HIT_NAMES_MAX}, each cut to {HIT_NAME_MAX_CHARS} characters; template_get lists "
        "them all"
    )


class RunnabilitySummary(BaseModel):
    """template_search's short form of template_get's runnability check. A kind with nothing missing is left out,
    so a runnable template's summary is {"runnable": true}."""

    @model_serializer(mode="wrap")
    def _drop_none(self, handler: Callable[[Any], dict[str, Any]]) -> dict[str, Any]:
        return {k: v for k, v in handler(self).items() if v is not None or k == "runnable"}

    runnable: bool | None = Field(
        description="As template_get's runnability.runnable. null: the template couldn't be checked; unchecked says why"
    )
    unchecked: str | None = Field(
        default=None,
        description="Why runnable is null: `timeout` (the template, a model folder it names, or /object_info wasn't "
        "read in time; a later search may check it), the error code reading the template, one of those folders or "
        "/object_info gave, or `check_failed` (the relay's own check failed)",
    )
    missing_nodes: Missing | None = Field(default=None, description="Node classes this instance lacks")
    missing_models: Missing | None = Field(default=None, description="Declared models not on disk, by file name")
    models_need_value_change: Missing | None = Field(
        default=None, description="Declared models on disk only in a subfolder, by file name"
    )
    missing_inputs: Missing | None = Field(default=None, description="Input files the input directory lacks")
    api_nodes: Missing | None = Field(default=None, description="Partner-API node classes")


def _missing(names: list[str]) -> Missing | None:
    if not names:
        return None
    return Missing(count=len(names), first=[_capped(n, HIT_NAME_MAX_CHARS) for n in names[:HIT_NAMES_MAX]])


def _summary(check: Runnability | str) -> RunnabilitySummary:
    """The hit's summary of a check, or of why there is none (a str)."""
    if isinstance(check, str):
        return RunnabilitySummary(runnable=None, unchecked=check)
    return RunnabilitySummary(
        runnable=check.runnable,
        missing_nodes=_missing([m.class_type for m in check.missing_nodes]),
        missing_models=_missing([m.name for m in check.missing_models]),
        models_need_value_change=_missing([m.name for m in check.models_need_value_change]),
        missing_inputs=_missing([m.file for m in check.missing_inputs]),
        api_nodes=_missing(check.api_nodes),
    )


class TemplateHit(_Compact):
    name: str = Field(description="Pass it to template_get")
    title: str
    description: str | None = None
    category: str
    tags: list[str]
    model_families: list[str] | None = None
    media_type: str | None = None
    partner_api: bool = Field(description="The index marks it as using partner-API (paid) nodes")
    min_comfyui_version: str | None = None
    tutorial_url: str | None = None


class TemplateSearchHit(TemplateHit):
    """A template_search hit. task to freshness come from /templates/index.mcp.json, when ComfyUI serves it and
    lists the template."""

    runnability: RunnabilitySummary

    task: str | None = Field(default=None, description="What it does, in a few words: 'Image to Video'")
    inputs: list[str] | None = Field(default=None, description="What it takes, in prose: 'image: Starting frame'")
    outputs: list[str] | None = Field(default=None, description="What it makes, in prose")
    capabilities: list[str] | None = Field(default=None, description="Workflow tags: 'image-to-video', 'lora'")
    recommend: str | None = Field(
        default=None,
        description="The index's tier, mostly from usage, best first: highly_recommended, top, high, medium, low, "
        "not_recommended",
    )
    freshness: str | None = Field(default=None, description="new, recent, current or established")


class TemplateSearchResult(BaseModel):
    query: str
    total_matches: int = Field(description="Matches left after the partner-API and runnable_only filters")
    hidden_partner_api: int = Field(description="Matches left out because they use partner-API nodes")
    hidden_not_runnable: int = Field(description="Matches runnable_only left out because their check found a gap")
    unchecked: int = Field(
        description="Matches whose runnability couldn't be checked (runnable null); runnable_only leaves them out"
    )
    source: dict[str, Any] = Field(
        description="The templates package, and `index`: index.mcp.json when ComfyUI's agent index added to at "
        "least one template (hits it lists carry task, inputs, outputs, capabilities, recommend and freshness), "
        "else index.json"
    )
    results: list[TemplateSearchHit]


# The largest workflow template_get returns, as the pretty-printed JSON the SDK
# sends as text: about 20k tokens, under the roughly 25k-token output limit
# common MCP clients apply (Claude Code's default). 512 of the 564 templates in
# comfyui-workflow-templates 0.11.66 fit; the largest is about 500k.
WORKFLOW_MAX_CHARS = 80_000


class TemplateDetail(TemplateHit):
    runnability: Runnability
    author: str | None = None
    source: dict[str, Any]
    workflow: dict[str, Any] | None = Field(
        default=None, description="The template in the frontend's UI format (nodes, links, subgraph definitions)"
    )


def _active_nodes(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    """The nodes that run: top level and inside subgraphs, skipping muted and bypassed ones."""
    definitions = workflow.get("definitions") if isinstance(workflow.get("definitions"), dict) else {}
    subgraphs = {
        s["id"]: s
        for s in definitions.get("subgraphs") or []
        if isinstance(s, dict) and isinstance(s.get("id"), str) and isinstance(s.get("nodes"), list)
    }
    active: list[dict[str, Any]] = []

    def walk(nodes: list[Any], inside: frozenset[str]) -> None:
        for node in nodes:
            if not isinstance(node, dict) or node.get("mode") in INACTIVE_MODES:
                continue
            kind = node.get("type")
            if kind in subgraphs:
                if kind not in inside:
                    walk(subgraphs[kind]["nodes"], inside | {kind})
            elif isinstance(kind, str) and kind not in FRONTEND_ONLY:
                active.append(node)

    walk(workflow["nodes"], frozenset())
    return active


def _declared_models(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for node in nodes:
        props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        for model in props.get("models") or []:
            if (
                isinstance(model, dict)
                and isinstance(model.get("name"), str)
                and isinstance(model.get("directory"), str)
            ):
                seen.setdefault((model["directory"], model["name"]), model)
    return list(seen.values())


def _on_disk(name: str, files: list[str]) -> str | None:
    """Where `name` is among a folder's files: itself, a path in a subfolder with that file name, or None."""
    if name in files:
        return name
    return next((f for f in files if f.rsplit("/", 1)[-1] == name), None)


# The core loaders whose file input is a COMBO of the input directory's
# contents, so /object_info already lists what is there.
INPUT_LOADERS = {"LoadImage": "image", "LoadImageMask": "image", "LoadAudio": "audio", "LoadVideo": "file"}


def _combo_values(spec: Any) -> list[Any] | None:
    if not isinstance(spec, list) or not spec:
        return None
    if isinstance(spec[0], list):
        return spec[0]
    opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    return opts.get("options") if isinstance(opts.get("options"), list) else None


@dataclass(frozen=True)
class Requirements:
    """What a template needs, read from its workflow alone, so it holds for as long as the templates version does
    (TemplateCache). _runnability checks it against the live instance."""

    uses: dict[str, int]  # active node class -> how many nodes of it
    packs: dict[str, str]  # node class -> the pack (cnr_id) the template names for it
    models: tuple[dict[str, Any], ...]  # declared models: name, directory and url
    inputs: tuple[tuple[str, str, str], ...]  # (loader class, input, file) for each loader value not fed by a link


def _loader_inputs(nodes: list[dict[str, Any]]) -> tuple[tuple[str, str, str], ...]:
    found: dict[tuple[str, str], tuple[str, str, str]] = {}
    for node in nodes:
        kind = node["type"]
        field = INPUT_LOADERS.get(kind)
        if field is None:
            continue
        linked = any(
            isinstance(i, dict) and i.get("name") == field and i.get("link") is not None
            for i in node.get("inputs") or []
        )
        named, values = node.get("widgets_values_named"), node.get("widgets_values")
        if isinstance(named, dict) and field in named:
            value = named[field]
        else:
            value = values[0] if isinstance(values, list) and values else None
        if not linked and isinstance(value, str) and value:
            found.setdefault((kind, value), (kind, field, value))
    return tuple(found.values())


def _requirements(workflow: dict[str, Any]) -> Requirements:
    nodes = _active_nodes(workflow)
    packs: dict[str, str] = {}
    for node in nodes:
        props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        if isinstance(props.get("cnr_id"), str):
            packs.setdefault(node["type"], props["cnr_id"])
    models = tuple(
        {"name": m["name"], "directory": m["directory"], "url": m.get("url") if isinstance(m.get("url"), str) else None}
        for m in _declared_models(nodes)
    )
    return Requirements(dict(Counter(n["type"] for n in nodes)), packs, models, _loader_inputs(nodes))


def _missing_inputs(inputs: Iterable[tuple[str, str, str]], object_info: dict[str, Any]) -> list[MissingInput]:
    missing = []
    for kind, field, value in inputs:
        spec = ((object_info.get(kind) or {}).get("input") or {}).get("required", {}).get(field)
        available = _combo_values(spec)
        if available is not None and value not in available:
            missing.append(MissingInput(class_type=kind, input=field, file=value))
    return missing


def _api_nodes(needs: Requirements, object_info: dict[str, Any]) -> list[str]:
    return sorted(t for t in needs.uses if partner_signals(object_info.get(t)))


def _runnability(needs: Requirements, object_info: dict[str, Any], folders: dict[str, list[str] | None]) -> Runnability:
    uses = needs.uses
    missing_nodes = [
        MissingNode(class_type=t, pack=needs.packs.get(t), count=c) for t, c in uses.items() if t not in object_info
    ]
    api_nodes = _api_nodes(needs, object_info)
    models = needs.models
    missing_models, misplaced = [], []
    for m in models:
        found = _on_disk(m["name"], folders.get(m["directory"]) or [])
        if found is None:
            missing_models.append(
                MissingModel(
                    name=m["name"],
                    directory=m["directory"],
                    url=m.get("url") if isinstance(m.get("url"), str) else None,
                    folder_known=folders.get(m["directory"]) is not None,
                )
            )
        elif found != m["name"]:
            misplaced.append(
                MisplacedModel(
                    name=m["name"],
                    directory=m["directory"],
                    found_at=found,
                    needs_value_change=f"set the loader's value from {m['name']!r} to {found!r}",
                )
            )
    missing_inputs = _missing_inputs(needs.inputs, object_info)
    return Runnability(
        runnable=not (missing_nodes or missing_models or misplaced or missing_inputs or api_nodes),
        missing_nodes=missing_nodes,
        missing_models=missing_models,
        models_need_value_change=misplaced,
        missing_inputs=missing_inputs,
        api_nodes=api_nodes,
        node_classes_checked=len(uses),
        models_checked=len(models),
    )


async def _folder_files(comfyui: ComfyUIClient, needs: Iterable[Requirements]) -> dict[str, list[str] | None]:
    """The files in every folder the templates' models name, fetched once each; None for a folder ComfyUI lacks."""
    wanted = sorted({m["directory"] for n in needs for m in n.models} - DOT_SEGMENTS)

    async def files(folder: str) -> list[str] | None:
        try:
            return await comfyui.model_files(folder)
        except ComfyUIError as exc:
            if exc.detail.get("status") == 404:
                return None
            raise

    return dict(zip(wanted, await _gather_limited(lambda f=f: files(f) for f in wanted), strict=True))


# Requirements are cached for one templates version at a time: comfyui-workflow-templates 0.11.66 serves 564
# templates, so this bounds the cache well above a whole package without letting it grow unchecked.
TEMPLATE_CACHE_MAX = 2048
# Checking every match is optional (it only ranks and filters), so template_search never waits longer than this
# for the templates the cache lacks, nor again as long for the model folders they declare; whatever is still
# unread is reported unchecked. Fetching all 564 templates of 0.11.66 from a local ComfyUI took about half a
# second at FETCH_CONCURRENCY.
TEMPLATE_FETCH_SECONDS = 5.0
MODEL_FOLDERS_SECONDS = 5.0
# /object_info is 1.8 MB at v0.37.0, and more with many custom nodes, so template_search gives it longer than the
# other reads; without it every match is unchecked. template_get waits for it as long as the client allows.
OBJECT_INFO_SECONDS = 15.0
# A search takes one of its own slots before it queues at the shared gate (cache.gate), so at most this many of
# its fetches wait there at once. Another search's fetches then queue behind those few, not behind every template
# the first one still has to read: the two-level gate gives the fairness, so this can equal the shared limit and
# a lone search still fetches at full concurrency.
SEARCH_FETCH_CONCURRENCY = FETCH_CONCURRENCY


class TemplateCache:
    """Each template's Requirements, by name, for the one templates version (installed_templates_version in
    /system_stats) they were read from. A template's file never changes within a version, so only the live side
    of a check (/object_info, /models/<folder>) is read again on each search. Another version empties the cache;
    an unknown version is never cached. At most max_entries, least recently used dropped first.

    `gate` is the relay's one limit on template fetches, shared by every search, so concurrent cold searches still
    ask ComfyUI for at most FETCH_CONCURRENCY templates at once. `fetching` holds the templates being read right
    now, so a search that wants one of them waits for that read instead of making its own."""

    def __init__(self, max_entries: int = TEMPLATE_CACHE_MAX) -> None:
        self.max_entries = max_entries
        self.version: str | None = None
        self._entries: OrderedDict[str, Requirements] = OrderedDict()
        self.gate = asyncio.Semaphore(FETCH_CONCURRENCY)
        self.fetching: dict[str, asyncio.Event] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, version: str | None, name: str) -> Requirements | None:
        if version is None or version != self.version or name not in self._entries:
            return None
        self._entries.move_to_end(name)
        return self._entries[name]

    def put(self, version: str | None, name: str, needs: Requirements) -> None:
        if version is None:
            return
        if version != self.version:
            self._entries.clear()
            self.version = version
        self._entries[name] = needs
        self._entries.move_to_end(name)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)


async def _bounded(jobs: dict[str, Callable[[], Awaitable[Any]]], seconds: float) -> dict[str, Any]:
    """Each job's answer. A job not done within `seconds` in all is cancelled and answers `timeout`, and a job that
    raises answers why: a RelayError's code, or `check_failed` for anything else. No job fails the caller."""
    out: dict[str, Any] = {}

    async def run(key: str, job: Callable[[], Awaitable[Any]]) -> None:
        try:
            out[key] = await job()
        except RelayError as exc:
            out[key] = exc.code
        except Exception:  # a bug in a check is that check's answer, not the call's failure
            log.exception("template_search: the check of %r failed", key)
            out[key] = "check_failed"

    tasks = [asyncio.ensure_future(run(k, j)) for k, j in jobs.items()]
    try:
        if tasks:
            await asyncio.wait(tasks, timeout=seconds)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return {k: out.get(k, "timeout") for k in jobs}


async def _requirements_of(
    comfyui: ComfyUIClient, cache: TemplateCache, version: str | None, names: list[str]
) -> dict[str, Requirements | str]:
    """Each named template's Requirements, from the cache or else fetched (in the order given, at most
    SEARCH_FETCH_CONCURRENCY at once and through cache.gate, for at most TEMPLATE_FETCH_SECONDS), or a str saying
    why there are none: `timeout`, or the error code fetching it gave. Never raises for a template."""
    out: dict[str, Requirements | str] = {}
    todo = []
    for name in names:
        cached = cache.get(version, name)
        if cached is None:
            todo.append(name)
        else:
            out[name] = cached
    own = asyncio.Semaphore(SEARCH_FETCH_CONCURRENCY)

    async def read(name: str) -> Requirements | str:
        try:
            needs = _requirements(await comfyui.template(name))
        except ComfyUIError as exc:
            return exc.code
        except (AttributeError, KeyError, TypeError, ValueError):  # a workflow shaped unlike any template
            return "comfyui_bad_response"
        cache.put(version, name, needs)
        return needs

    async def fetch(name: str) -> Requirements | str:
        while True:
            cached = cache.get(version, name)  # another search may have read it meanwhile
            if cached is not None:
                return cached
            running = cache.fetching.get(name)
            if running is not None:  # another search is reading it: wait for that, holding no slot
                await running.wait()
                continue
            async with own, cache.gate:
                if name in cache.fetching or cache.get(version, name) is not None:
                    continue  # read, or started, while this one waited at the gates
                cache.fetching[name] = done = asyncio.Event()
                try:
                    return await read(name)
                finally:
                    del cache.fetching[name]
                    done.set()

    out.update(await _bounded({n: lambda n=n: fetch(n) for n in todo}, TEMPLATE_FETCH_SECONDS))
    return {name: out[name] for name in names}


async def _folder_files_or_why(comfyui: ComfyUIClient, needs: Iterable[Requirements]) -> dict[str, Any]:
    """As _folder_files, for at most MODEL_FOLDERS_SECONDS, but a folder ComfyUI fails to list (any status but
    404, a bad answer, no answer in time) answers a str saying why instead of failing the call."""
    wanted = sorted({m["directory"] for n in needs for m in n.models} - DOT_SEGMENTS)
    gate = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def files(folder: str) -> list[str] | str | None:
        async with gate:
            try:
                return await comfyui.model_files(folder)
            except ComfyUIError as exc:
                return None if exc.detail.get("status") == 404 else exc.code

    jobs = {f: lambda f=f: files(f) for f in wanted}
    return await _bounded(jobs, MODEL_FOLDERS_SECONDS)


async def _object_info_or_why(comfyui: ComfyUIClient) -> dict[str, dict[str, Any]] | str:
    """/object_info within OBJECT_INFO_SECONDS, or why not: `timeout`, or the error code reading it gave.
    template_search then reports every match unchecked."""
    try:
        return _checked_object_info(await asyncio.wait_for(comfyui.object_info(), OBJECT_INFO_SECONDS))
    except TimeoutError:
        return "timeout"
    except ComfyUIError as exc:
        return exc.code


def _checks(
    needs: dict[str, Requirements | str], object_info: dict[str, Any], folders: dict[str, Any]
) -> tuple[dict[str, Runnability | str], set[str]]:
    """Each template's runnability, or why it has none: its own fetch failed, a folder its models name couldn't
    be listed, or checking it against ComfyUI's data failed (`check_failed`). And the templates whose graph uses
    a partner-API node, known whenever the template and /object_info were read, even if a folder wasn't."""
    listed = {f: files for f, files in folders.items() if not isinstance(files, str)}
    out: dict[str, Runnability | str] = {}
    partner: set[str] = set()
    for name, n in needs.items():
        if isinstance(n, str):
            out[name] = n
            continue
        try:
            if _api_nodes(n, object_info):
                partner.add(name)
            failed = next(
                (folders[m["directory"]] for m in n.models if isinstance(folders.get(m["directory"]), str)), None
            )
            out[name] = failed or _runnability(n, object_info, listed)
        except Exception:  # /object_info is untrusted: a shape no check expects is that template's answer
            log.exception("template_search: the check of %r failed", name)
            out[name] = "check_failed"
    return out, partner


def _index_entries(index: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(template, its category) for every template in the index."""
    entries = []
    for category in index:
        for template in category.get("templates") or []:
            if not isinstance(template, dict) or not isinstance(template.get("name"), str):
                raise _bad("a /templates/index.json entry with no name")
            if template["name"] not in DOT_SEGMENTS:
                entries.append((template, category))
    return entries


def _strings(value: Any) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else []


def _capped(text: str, limit: int | None) -> str:
    return text[: limit - 1].rstrip() + "…" if limit and len(text) > limit else text


def _mcp_entries(index: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """index.mcp.json's templates by name. index.json stays the catalogue (it has the tags, the partner-API flag
    and templates this one leaves out); this only adds to the entries it shares a name with."""
    return {
        t["name"]: t
        for c in index or []
        for t in c.get("templates") or []
        if isinstance(t, dict) and isinstance(t.get("name"), str)
    }


# What a search hit keeps of index.mcp.json: enough to choose by, not a page per hit. Every string is capped,
# since the index is ComfyUI's data, not ours.
IO_MAX_CHARS, IO_MAX_ITEMS, CAPABILITIES_MAX, WORD_MAX_CHARS = 120, 4, 8, 40
# The agent index only adds to a search, so it never holds one up for long, and any failure skips it.
AGENT_INDEX_SECONDS = 5.0


async def _agent_index(comfyui: ComfyUIClient) -> list[dict[str, Any]] | None:
    """/templates/index.mcp.json, or None when ComfyUI can't serve it in AGENT_INDEX_SECONDS, for whatever reason
    (404, any other status, a body that isn't an index, no answer): the search then uses index.json alone."""
    try:
        return await asyncio.wait_for(comfyui.templates_mcp_index(), AGENT_INDEX_SECONDS)
    except (ComfyUIError, TimeoutError):
        return None


def _agent_fields(mcp: dict[str, Any]) -> dict[str, Any]:
    """The fields of an index.mcp.json entry that help choose a template, capped."""
    io = mcp.get("io") if isinstance(mcp.get("io"), dict) else {}
    caps = mcp.get("capabilities") if isinstance(mcp.get("capabilities"), dict) else {}

    def text(key: str) -> str | None:
        return _capped(mcp[key], WORD_MAX_CHARS) if isinstance(mcp.get(key), str) else None

    def capped(items: Any, count: int, chars: int) -> list[str] | None:
        return [_capped(s, chars) for s in _strings(items)[:count]] or None

    return {
        "task": text("task"),
        "inputs": capped(io.get("inputs"), IO_MAX_ITEMS, IO_MAX_CHARS),
        "outputs": capped(io.get("outputs"), IO_MAX_ITEMS, IO_MAX_CHARS),
        "capabilities": capped(caps.get("workflow"), CAPABILITIES_MAX, WORD_MAX_CHARS),
        "recommend": text("recommend"),
        "freshness": text("freshness"),
    }


def _hit_fields(
    template: dict[str, Any],
    category: dict[str, Any],
    description_limit: int | None,
    mcp: dict[str, Any] | None = None,
) -> dict[str, Any]:
    description = next(
        (d for d in ((mcp or {}).get("description"), template.get("description")) if isinstance(d, str)), None
    )
    if description:
        description = _capped(description, description_limit)
    return {
        **(_agent_fields(mcp) if mcp else {}),
        "name": template["name"],
        "title": str(template.get("title") or template["name"]),
        "description": description,
        "category": " / ".join(str(c) for c in (category.get("category"), category.get("title")) if c),
        "tags": _strings(template.get("tags")),
        "model_families": _strings(template.get("models")) or None,
        "media_type": template.get("mediaType") if isinstance(template.get("mediaType"), str) else None,
        "partner_api": template.get("openSource") is False,
        "min_comfyui_version": template.get("minComfyUIVersion")
        if isinstance(template.get("minComfyUIVersion"), str)
        else None,
        "tutorial_url": template.get("tutorialUrl") if isinstance(template.get("tutorialUrl"), str) else None,
    }


def _template_fields(
    template: dict[str, Any], category: dict[str, Any], mcp: dict[str, Any] | None = None
) -> tuple[tuple[int, str], ...]:
    """The searchable text, weighted: the title and name 3; tags, model families, and index.mcp.json's task,
    model and capabilities 2; the rest, with index.mcp.json's description and io prose, 1."""
    mcp = mcp or {}
    io = mcp.get("io") if isinstance(mcp.get("io"), dict) else {}
    caps = mcp.get("capabilities") if isinstance(mcp.get("capabilities"), dict) else {}
    fields = (
        (3, f"{template.get('title', '')} {template['name'].replace('_', ' ')}"),
        (
            2,
            " ".join(
                _strings(template.get("tags"))
                + _strings(template.get("models"))
                + [str(mcp.get("task") or ""), str(mcp.get("model") or "")]
                + _strings(caps.get("workflow"))
            ),
        ),
        (
            1,
            " ".join(
                [str(template.get("description", "")), str(mcp.get("description") or "")]
                + _strings(io.get("inputs"))
                + _strings(io.get("outputs"))
                + [str(category.get("title", "")), str(category.get("category", ""))]
            ),
        ),
    )
    return tuple((weight, str(text).lower()) for weight, text in fields)


def _template_score(
    words: list[str], fields: tuple[tuple[int, str], ...], rarity: dict[str, float]
) -> tuple[int, float]:
    """(query words matched, score). Each matched word adds its field's weight times its rarity across the
    index, so "sd1.5" outweighs "image", which nearly every template mentions."""
    matched, score = 0, 0.0
    for word in words:
        weight = max((w for w, text in fields if word in text), default=0)
        matched += weight > 0
        score += weight * rarity[word]
    return matched, score


async def _source(comfyui: ComfyUIClient) -> dict[str, Any]:
    stats = await comfyui.system_stats()
    return {**TEMPLATES_SOURCE, "version": stats["system"].get("installed_templates_version")}


def _template_search(relay: Relay) -> Callable[..., Any]:
    async def template_search(
        query: str = Field(min_length=1, description="The goal, in a few words: 'text to image', 'upscale video'"),
        limit: int = Field(default=5, ge=1, le=20),
        include_partner_api: bool = Field(
            default=False, description="Also return templates built on partner-API (paid) nodes"
        ),
        runnable_only: bool = Field(
            default=False,
            description="Return only templates this instance can run now (runnable true); unchecked ones are left out",
        ),
    ) -> TemplateSearchResult:
        """Find ComfyUI workflow templates (the ones the ComfyUI frontend's template browser offers) for a goal,
        by title, name, tags, model family, description and category, and check each match against the live
        instance.

        When ComfyUI serves its agent index (/templates/index.mcp.json; v0.37.0 does), the search also matches
        each template's task, inputs and outputs, and capabilities, and a hit carries them, with the index's
        recommend and freshness, to choose by. source.index says whether it was used; if ComfyUI can't serve it,
        the search runs on index.json alone.

        Hits are ranked by how many query words they match, then runnable before not, then relevance. With a
        one-word query every match ties on words matched, so runnable templates come first. Each hit's
        runnability summarises what this instance is missing for it: counts and the first few names of node
        classes, declared models, models on disk only under another path, input files its loaders name, and
        partner-API nodes; template_get gives the full lists. runnable is true only when none of those is found;
        it does not validate the graph itself, models named only in widget values, or memory. runnable is null
        when the check couldn't be made in time (the template, a model folder it names, or /object_info couldn't
        be read; unchecked says why); the search still answers. runnable_only keeps only runnable templates.
        Templates built on partner-API nodes, which spend credits, are left out unless include_partner_api is
        true. Fetch one with template_get.
        """
        words = _words(query)
        if not words:
            raise _invalid_query(query)
        index, mcp_index, object_info, source = await asyncio.gather(
            relay.comfyui.templates_index(),
            _agent_index(relay.comfyui),
            _object_info_or_why(relay.comfyui),
            _source(relay.comfyui),
        )
        listed = _index_entries(index)
        mcp = _mcp_entries(mcp_index)
        source["index"] = "index.mcp.json" if any(t["name"] in mcp for t, _ in listed) else "index.json"
        entries = [(t, c, _template_fields(t, c, mcp.get(t["name"]))) for t, c in listed]
        rarity = {
            w: math.log((len(entries) + 1) / (1 + sum(any(w in text for _, text in f) for _, _, f in entries))) + 1
            for w in set(words)
        }
        scored, hidden = [], 0
        for template, category, fields in entries:
            matched, score = _template_score(words, fields, rarity)
            if not matched:
                continue
            if template.get("openSource") is False and not include_partner_api:
                hidden += 1
                continue
            usage = template.get("usage") if isinstance(template.get("usage"), int) else 0
            scored.append(((matched, score, usage), template, category))
        # Fetched best first, so a search cut short by TEMPLATE_FETCH_SECONDS has checked its likeliest hits.
        scored.sort(key=lambda s: (-s[0][0], -s[0][1], -s[0][2]))
        names = [t["name"] for _, t, _ in scored]
        checks: dict[str, Runnability | str]
        # The index's openSource flag is the index's word; a graph's partner-API nodes are the graph's.
        partner: set[str] = set()
        if isinstance(object_info, str):  # no live side to check against: every match is unchecked
            checks = dict.fromkeys(names, object_info)
        else:
            version = source.get("version") if isinstance(source.get("version"), str) else None
            needs = await _requirements_of(relay.comfyui, relay.template_requirements, version, names)
            folders = await _folder_files_or_why(
                relay.comfyui, (n for n in needs.values() if isinstance(n, Requirements))
            )
            checks, partner = _checks(needs, object_info, folders)
        kept, not_runnable, unchecked = [], 0, 0
        for rank, template, category in scored:
            check = checks[template["name"]]
            if template["name"] in partner and not include_partner_api:
                hidden += 1
                continue
            if isinstance(check, str):
                unchecked += 1
                if runnable_only:
                    continue
            elif runnable_only and not check.runnable:
                not_runnable += 1
                continue
            kept.append((rank, template, category, check))
        # Runnable only breaks ties between templates that match as many query words: never outright first.
        kept.sort(key=lambda k: (-k[0][0], not (isinstance(k[3], Runnability) and k[3].runnable), -k[0][1], -k[0][2]))
        return TemplateSearchResult(
            query=query,
            total_matches=len(kept),
            hidden_partner_api=hidden,
            hidden_not_runnable=not_runnable,
            unchecked=unchecked,
            source=source,
            results=[
                TemplateSearchHit(**_hit_fields(t, c, 240, mcp.get(t["name"])), runnability=_summary(check))
                for _, t, c, check in kept[:limit]
            ],
        )

    return template_search


def _template_get(relay: Relay) -> Callable[..., Any]:
    async def template_get(
        name: str = Field(min_length=1, description="The template's name, as template_search returns it"),
        include_workflow: bool = Field(
            default=True, description="false returns only the metadata and runnability, not the workflow"
        ),
    ) -> TemplateDetail:
        """Fetch one ComfyUI workflow template by name: its metadata, a runnability check against the live
        instance (the same one template_search reports), and the workflow itself.

        The workflow is in the frontend's UI format (nodes with widgets_values, links, subgraph definitions), as
        the ComfyUI frontend loads it, not the API format /prompt takes. A workflow too large to return (over
        80,000 characters as JSON) fails with `workflow_too_large`; include_workflow=false still returns its
        metadata and runnability. An unknown name fails with `unknown_template` and close matches.
        """
        name = name.removesuffix(".json")
        index, object_info, source = await asyncio.gather(
            relay.comfyui.templates_index(), relay.comfyui.object_info(), _source(relay.comfyui)
        )
        _checked_object_info(object_info)
        entries = _index_entries(index)
        found = next(((t, c) for t, c in entries if t["name"] == name), None)
        if found is None:
            suggestions = _close_matches(name, ((t["name"], str(t.get("title") or t["name"])) for t, _ in entries))
            raise RelayError(
                "unknown_template",
                f"ComfyUI serves no template named {name!r}; find one with template_search.",
                suggestions=[{"name": s["id"], "title": s["display_name"]} for s in suggestions],
            )
        template, category = found
        workflow = await relay.comfyui.template(name)
        if include_workflow:
            size = len(json.dumps(workflow, indent=2, ensure_ascii=False))
            if size > WORKFLOW_MAX_CHARS:
                raise RelayError(
                    "workflow_too_large",
                    f"Template {name!r} is {size} characters as JSON, over the {WORKFLOW_MAX_CHARS} this tool "
                    "returns: most MCP clients cut a result that long. Call it again with include_workflow=false "
                    "for its metadata and runnability, or choose a smaller template.",
                    size=size,
                    limit=WORKFLOW_MAX_CHARS,
                )
        needs = _requirements(workflow)
        folders = await _folder_files(relay.comfyui, [needs])
        return TemplateDetail(
            **_hit_fields(template, category, None),
            author=template.get("username") if isinstance(template.get("username"), str) else None,
            source=source,
            runnability=_runnability(needs, object_info, folders),
            workflow=workflow if include_workflow else None,
        )

    return template_get


INTROSPECTION_TOOLS: tuple[tuple[str, frozenset[str], Callable[[Relay], Callable[..., Any]], ToolAnnotations], ...] = (
    ("node_search", READ, _node_search, READ_ONLY),
    ("node_describe", READ, _node_describe, READ_ONLY),
    ("model_list", READ, _model_list, READ_ONLY),
    ("template_search", READ, _template_search, READ_ONLY),
    ("template_get", READ, _template_get, READ_ONLY),
)
