"""The `read` profile's introspection tools (#133): nodes, models and templates.

Every answer comes from the live ComfyUI this relay serves, through
`ComfyUIClient`, so it matches what that instance will actually accept:

    node_search      /object_info, ranked for a query
    node_describe    /object_info/<class>, rendered as a full input/output spec
    model_list       /models and /models/<folder>
    template_search  /templates/index.json, plus a runnability check per hit
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
import math
import re
from collections import Counter
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, Literal

from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field, model_serializer

from .comfyui import ComfyUIClient, ComfyUIError
from .errors import RelayError

if TYPE_CHECKING:
    from .tools import Relay

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
                key = (tier, bool(node.get("deprecated")), bool(node.get("api_node")), len(class_type), class_type)
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
                    api_node=True if node.get("api_node") else None,
                    deprecated=True if node.get("deprecated") else None,
                )
                for key, class_type, node in ranked[:limit]
            ],
        )

    return node_search


# -- node_describe ------------------------------------------------------------

# ComfyUI's dynamic V3 inputs (comfy_api/latest/_io.py). Inside one, every
# input's name is fully qualified with dots (finalize_prefix): a DynamicCombo
# `resize_type` set to "scale dimensions" adds `resize_type.width`, and an
# Autogrow `images` with prefix "image" takes `images.image0`, `images.image1`
# and so on. Those qualified names are the keys a graph's inputs must use.
AUTOGROW = "COMFY_AUTOGROW_V3"
DYNAMIC_COMBO = "COMFY_DYNAMICCOMBO_V3"
DYNAMIC_SLOT = "COMFY_DYNAMICSLOT_V3"
MATCH_TYPE = "COMFY_MATCHTYPE_V3"
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


AutogrowSpec.model_rebuild()


def _number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _cut(values: list[Any], limit: int) -> tuple[list[Any], int, bool | None]:
    return values[:limit], len(values), True if len(values) > limit else None


def _autogrow(qname: str, template: dict[str, Any], required: bool, max_options: int) -> AutogrowSpec | None:
    """ComfyUI's Autogrow._expand_schema_for_dynamic, as a naming rule: `<qname>.<name>` for each name."""
    prefix = template.get("prefix") if isinstance(template.get("prefix"), str) else None
    if isinstance(template.get("names"), list):
        names = [str(n) for n in template["names"]]
    elif prefix is not None and isinstance(template.get("max"), int):
        names = [f"{prefix}{i}" for i in range(template["max"])]
    else:
        return None
    item = None
    sections = template.get("input") if isinstance(template.get("input"), dict) else {}
    for section, specs in sections.items():
        if isinstance(specs, dict) and specs:
            label = f"{qname}.{prefix}<n>" if prefix is not None else f"{qname}.<name>"
            item = _input([], label, next(iter(specs.values())), required and section == "required", max_options)
            break
    if item is None:
        return None
    shown, total, truncated = _cut([f"{qname}.{n}" for n in names], max_options)
    minimum = template.get("min") if isinstance(template.get("min"), int) else 1
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
    qname = ".".join([*path, name])
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
        api_node=bool(info.get("api_node")),
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
        An unknown class fails with `unknown_node_class` and a `suggestions` list of close class names.
        """
        found = {} if class_type in DOT_SEGMENTS else await relay.comfyui.object_info(class_type)
        if class_type in found:
            if not isinstance(found[class_type], dict):
                raise _bad(f"an /object_info/{class_type} that is not an object")
            return _spec(class_type, found[class_type], max_options)
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
    runnability: Runnability


class TemplateSearchResult(BaseModel):
    query: str
    total_matches: int
    hidden_partner_api: int = Field(description="Matches left out because they use partner-API nodes")
    source: dict[str, Any]
    results: list[TemplateHit]


# The largest workflow template_get returns, as the pretty-printed JSON the SDK
# sends as text: about 20k tokens, under the roughly 25k-token output limit
# common MCP clients apply (Claude Code's default). 512 of the 564 templates in
# comfyui-workflow-templates 0.11.66 fit; the largest is about 500k.
WORKFLOW_MAX_CHARS = 80_000


class TemplateDetail(TemplateHit):
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


def _missing_inputs(nodes: list[dict[str, Any]], object_info: dict[str, Any]) -> list[MissingInput]:
    missing: dict[tuple[str, str], MissingInput] = {}
    for node in nodes:
        kind = node["type"]
        field = INPUT_LOADERS.get(kind)
        spec = ((object_info.get(kind) or {}).get("input") or {}).get("required", {}).get(field) if field else None
        available = _combo_values(spec)
        if available is None:
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
        if linked or not isinstance(value, str) or not value or value in available:
            continue
        missing.setdefault((kind, value), MissingInput(class_type=kind, input=field, file=value))
    return list(missing.values())


def _runnability(
    workflow: dict[str, Any], object_info: dict[str, Any], folders: dict[str, list[str] | None]
) -> Runnability:
    nodes = _active_nodes(workflow)
    uses = Counter(n["type"] for n in nodes)
    packs: dict[str, str] = {}
    for node in nodes:
        props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        if isinstance(props.get("cnr_id"), str):
            packs.setdefault(node["type"], props["cnr_id"])
    missing_nodes = [
        MissingNode(class_type=t, pack=packs.get(t), count=c) for t, c in uses.items() if t not in object_info
    ]
    api_nodes = sorted(t for t in uses if object_info.get(t, {}).get("api_node"))
    models = _declared_models(nodes)
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
    missing_inputs = _missing_inputs(nodes, object_info)
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


async def _folder_files(comfyui: ComfyUIClient, workflows: list[dict[str, Any]]) -> dict[str, list[str] | None]:
    """The files in every folder the workflows' models name, fetched once each; None for a folder ComfyUI lacks."""
    wanted = sorted({m["directory"] for w in workflows for m in _declared_models(_active_nodes(w))} - DOT_SEGMENTS)

    async def files(folder: str) -> list[str] | None:
        try:
            return await comfyui.model_files(folder)
        except ComfyUIError as exc:
            if exc.detail.get("status") == 404:
                return None
            raise

    return dict(zip(wanted, await _gather_limited(lambda f=f: files(f) for f in wanted), strict=True))


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


def _hit_fields(template: dict[str, Any], category: dict[str, Any], description_limit: int | None) -> dict[str, Any]:
    description = template.get("description") if isinstance(template.get("description"), str) else None
    if description and description_limit and len(description) > description_limit:
        description = description[: description_limit - 1].rstrip() + "…"
    return {
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


def _template_fields(template: dict[str, Any], category: dict[str, Any]) -> tuple[tuple[int, str], ...]:
    """The searchable text, weighted: the title and name 3, tags and model families 2, the rest 1."""
    fields = (
        (3, f"{template.get('title', '')} {template['name'].replace('_', ' ')}"),
        (2, " ".join(_strings(template.get("tags")) + _strings(template.get("models")))),
        (1, f"{template.get('description', '')} {category.get('title', '')} {category.get('category', '')}"),
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
    ) -> TemplateSearchResult:
        """Find ComfyUI workflow templates (the ones the ComfyUI frontend's template browser offers) for a goal,
        by title, description, tags and model family, and check each hit against the live instance.

        Each hit's runnability lists what this instance is missing for it: node classes, declared models (with
        their folder and source URL), models that are on disk only under another path, input files its loaders
        name, and partner-API nodes. runnable is true only when none of those is found; it does not validate the
        graph itself, models named only in widget values, or memory. Templates built on partner-API nodes, which
        spend credits, are left out unless include_partner_api is true. Fetch one with template_get.
        """
        words = _words(query)
        if not words:
            raise _invalid_query(query)
        index, object_info, source = await asyncio.gather(
            relay.comfyui.templates_index(), relay.comfyui.object_info(), _source(relay.comfyui)
        )
        _checked_object_info(object_info)
        entries = [(t, c, _template_fields(t, c)) for t, c in _index_entries(index)]
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
            scored.append(((-matched, -score, -usage), template, category))
        scored.sort(key=lambda s: s[0])
        top = scored[:limit]
        workflows = await _gather_limited(lambda t=t: relay.comfyui.template(t["name"]) for _, t, _ in top)
        folders = await _folder_files(relay.comfyui, workflows)
        results = [
            TemplateHit(**_hit_fields(t, c, 240), runnability=_runnability(w, object_info, folders))
            for (_, t, c), w in zip(top, workflows, strict=True)
        ]
        if not include_partner_api:
            # The index's openSource flag is the index's word; the check's api_nodes is the graph's.
            kept = [h for h in results if not h.runnability.api_nodes]
            hidden, results = hidden + len(results) - len(kept), kept
        return TemplateSearchResult(
            query=query,
            total_matches=len(scored) - (len(top) - len(results)),
            hidden_partner_api=hidden,
            source=source,
            results=results,
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
        folders = await _folder_files(relay.comfyui, [workflow])
        return TemplateDetail(
            **_hit_fields(template, category, None),
            author=template.get("username") if isinstance(template.get("username"), str) else None,
            source=source,
            runnability=_runnability(workflow, object_info, folders),
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
