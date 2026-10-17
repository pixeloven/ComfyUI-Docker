"""What a workflow needs that this ComfyUI lacks (#213): workflow_validate's `requirements`.

It is the template runnability check (tools_introspection: _requirements, _runnability) applied to any graph:

    UI format   the template check itself, on the graph's own node properties: node classes /object_info lacks,
                with the pack each node names (cnr_id, or aux_id for a git pack, and its ver); the models it
                declares (properties.models: folder, file name, source URL) that aren't on disk, or are only
                under another path (found_at); and the files its core loaders name that the input directory
                lacks.
    API format  no properties, so the graph's own values: node classes /object_info lacks, with close names; a
                value that names a file (it has an extension) and isn't among its input's COMBO options, which
                ComfyUI lists from a model folder: under another path (found_at), or missing, with close names
                from those options and the folder whose listing they are; and the core loaders' input files, as
                the template check reads them.

A UI graph this server converted is read both ways, so a model named only in a widget value is found too. One it
didn't convert is read from its properties alone, and says so: `satisfied` is then never true.

It only reports. Values and types are ComfyUI's to check at /prompt (#145), and nothing here installs or downloads:
the proposals are for a human or deployer to review and apply (#201, D1). Everything it says comes from the graph
it was given and from ComfyUI's own data, both capped. It is optional detail on workflow_validate, so it has a
total time bound, and a failure leaves it out and says why (requirements_unchecked) without failing the call. Its
one CPU-heavy part, the fuzzy suggestions, runs in a thread that checks a deadline and a stop flag between chunks
of work, so it ends with the call (jobs.py's rule for threads).
"""

from __future__ import annotations

import asyncio
import difflib
import heapq
import logging
import re
import threading
import time
import weakref
from collections import Counter
from collections.abc import Callable
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, Field, model_serializer

from .comfyui import ComfyUIClient, ComfyUIError
from .errors import RelayError
from .tools_introspection import (
    DISPLAY_NAME_MAX_CHARS,
    DOT_SEGMENTS,
    FETCH_CONCURRENCY,
    INPUT_LOADERS,
    MODEL_FOLDERS_SECONDS,
    NOT_MODEL_FOLDERS,
    SUGGEST_SECONDS,
    MisplacedModel,
    MissingInput,
    _active_nodes,
    _bounded,
    _capped,
    _closest,
    _combo_values,
    _Compact,
    _folder_files_or_why,
    _missing_inputs,
    _name_index,
    _names,
    _requirements,
    _runnability,
)

log = logging.getLogger("comfyrelay")

# The whole report gets this long, its model folder listings included; then it is left out (`timeout`).
REQUIREMENTS_SECONDS = 10.0
# Each list keeps at most this many entries (truncated says so), and so does each proposal map.
MAX_ITEMS = 50
# Suggestions: this many names each, for the first MAX_SUGGESTED missing classes and as many missing models.
MAX_SUGGESTIONS = 3
MAX_SUGGESTED = 10
# The suggestion scan checks its deadline and stop flag after each chunk of this many candidates.
SCAN_CHUNK = 2000
# A missing file name is compared by difflib with only this many names: those sharing the most character pairs.
PREFILTER = 50
# Strings from the graph's own properties (a pack id, a version, a URL) are cut to this width. A name ComfyUI
# lists, which an agent would put back into a graph (a class, a file path, a folder), is never cut: past its width
# it is left out instead (#206).
FIELD_MAX_CHARS = 200
URL_MAX_CHARS = 500
PATH_MAX_CHARS = 500
# Model folders listed for an API graph's folder match, and how long a listing is reused: as long as
# tools_workflow.OBJECT_INFO_TTL_SECONDS shares /object_info, since loaders list their options from the same place.
LISTINGS_TTL_SECONDS = 10.0
NOT_LISTED = NOT_MODEL_FOLDERS | DOT_SEGMENTS | {"datasets", "configs"}
# A COMBO value that names a file: an extension that starts with a letter, so "v1.5" or "1.0" are not files.
FILE_NAME = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,11}$")
# LoadImage and its kind validate their own values (VALIDATE_INPUTS): a subfolder path or a value annotated with
# the folder it is in is resolved by the node, not listed in its options, so it can't be checked from them.
ANNOTATED = re.compile(r"\[(input|output|temp)\]\s*$")
# A full git commit SHA, and the registry versions ComfyUI-Manager never pins (get_current_snapshot).
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
UNPINNED_VERSIONS = frozenset({"nightly", "latest", "unknown"})
# ComfyUI's own nodes carry this cnr_id: a missing one needs a newer ComfyUI, not a node pack.
CORE_PACK = "comfy-core"
HF_URL = re.compile(r"^/([^/]+/[^/]+)/(?:resolve|blob)/([^/]+)/(.+)$")
CIVITAI_URL = re.compile(r"^/api/download/models/(\d+)/?$")


class RequiredNode(_Compact):
    class_type: str
    count: int = Field(description="How many nodes of it the graph has")
    pack: str | None = Field(default=None, description="UI format: the registry pack (cnr_id) the node names")
    aux_id: str | None = Field(default=None, description="UI format: the git repository (owner/repo) the node names")
    version: str | None = Field(default=None, description="UI format: the pack version or commit the node names (ver)")
    hint: str | None = None
    suggestions: list[str] | None = Field(default=None, description="Close class names this ComfyUI has")


class RequiredModel(_Compact):
    name: str = Field(description="The file name the graph asks for")
    directory: str | None = Field(
        default=None,
        description="The model folder it belongs in; absent when the graph doesn't say and its "
        "loader's options match no one folder",
    )
    url: str | None = Field(default=None, description="UI format: where the node's properties.models say it comes from")
    folder_known: bool | None = Field(default=None, description="false: this ComfyUI has no such folder type")
    node_id: str | None = None
    class_type: str | None = None
    input: str | None = None
    suggestions: list[str] | None = Field(
        default=None, description="API format: close names among the loader's options"
    )


class ModelAtAnotherPath(_Compact, MisplacedModel):
    directory: str | None = None
    found_at: str | None = None
    candidates: list[str] | None = Field(
        default=None, description="Several files have this name: the paths to choose from, instead of found_at"
    )
    node_id: str | None = None
    class_type: str | None = None
    input: str | None = None


class RequiredInput(_Compact, MissingInput):
    node_id: str | None = None


class Proposals(_Compact):
    note: str
    comfy_yaml_models: list[dict[str, Any]] | None = Field(
        default=None, description="Entries for comfy.yaml's models: list, for the missing models with a source URL"
    )
    custom_nodes: dict[str, Any] | None = Field(
        default=None, description="A custom_nodes entry for comfy-lock.yaml, in ComfyUI-Manager's snapshot shape"
    )


class WorkflowRequirements(BaseModel):
    @model_serializer(mode="wrap")
    def _drop_none(self, handler: Callable[[Any], dict[str, Any]]) -> dict[str, Any]:
        return {k: v for k, v in handler(self).items() if v is not None or k == "satisfied"}

    format: Literal["ui", "api"] = Field(description="How it was read: ui (node properties), api (input values)")
    satisfied: bool | None = Field(
        description="true: nothing below is missing. null: nothing listed, but not everything could be checked "
        "(notes say what). It says nothing about values or types"
    )
    missing_nodes: list[RequiredNode]
    missing_models: list[RequiredModel]
    models_need_value_change: list[ModelAtAnotherPath] = Field(
        description="On disk only under another path: set the loader's value to found_at"
    )
    missing_inputs: list[RequiredInput] = Field(description="Files the loaders name that the input directory lacks")
    truncated: bool | None = Field(default=None, description=f"A list was cut at {MAX_ITEMS} entries")
    notes: list[str] | None = Field(default=None, description="What couldn't be checked, and why")
    proposals: Proposals | None = None


def _text(value: Any, limit: int = FIELD_MAX_CHARS) -> str | None:
    return _capped(value, limit) if isinstance(value, str) and value else None


def _tolerant(info: dict[str, Any]) -> dict[str, Any]:
    """/object_info with every entry no check can read (not an object, or with input sections that aren't) made
    empty: that class is still present, but its inputs and names are skipped rather than failing the report."""

    def readable(spec: Any) -> bool:
        if not isinstance(spec, dict):
            return False
        sections = spec.get("input", {})
        return isinstance(sections, dict) and all(
            isinstance(sections[s], dict) for s in ("required", "optional") if s in sections
        )

    return {k: v if readable(v) else {} for k, v in info.items()}


def _matches(name: str, files: list[str]) -> list[str]:
    """Where `name` is among a folder's files: itself, else every path in a subfolder with that file name. The
    template check's _on_disk, but every match, so several can be reported rather than the first chosen."""
    if name in files:
        return [name]
    return [f for f in files if f.rsplit("/", 1)[-1] == name]


def _moved(name: str, matches: list[str], **where: Any) -> ModelAtAnotherPath:
    usable = [m for m in matches if len(m) <= PATH_MAX_CHARS]
    if len(usable) == 1:
        return ModelAtAnotherPath(
            name=name,
            found_at=usable[0],
            needs_value_change=f"set the loader's value from {name!r} to {usable[0]!r}",
            **where,
        )
    if usable:
        return ModelAtAnotherPath(
            name=name,
            candidates=usable[:MAX_ITEMS],
            needs_value_change=f"{len(usable)} files are named {name!r}: set the loader's value to the one meant",
            **where,
        )
    return ModelAtAnotherPath(
        name=name, needs_value_change=f"on disk under a path over {PATH_MAX_CHARS} characters, not shown", **where
    )


def _checkable_input(file: str) -> bool:
    return "/" not in file and not ANNOTATED.search(file)


def _input_note(skipped: int) -> str:
    return (
        f"{skipped} input file value(s) name a subfolder or carry an [input]/[output]/[temp] annotation: the loader "
        "resolves those itself, so they weren't checked"
    )


# -- UI format: the template check ---------------------------------------------


def _node_sources(workflow: dict[str, Any]) -> dict[str, dict[str, str | None]]:
    """Each class's pack, repository and version, as the first active node of it names them in its properties."""
    found: dict[str, dict[str, str | None]] = {}
    for node in _active_nodes(workflow):
        props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        found.setdefault(
            node["type"],
            {
                "pack": _text(props.get("cnr_id")),
                "aux_id": _text(props.get("aux_id")),
                "version": _text(props.get("ver")),
            },
        )
    return found


def _core_hint(source: dict[str, str | None]) -> str | None:
    if source.get("pack") != CORE_PACK:
        return None
    made = f" {source['version']}" if source.get("version") else ""
    return f"one of ComfyUI's own nodes (comfy-core{made}): a newer ComfyUI may be needed; no node pack provides it"


async def _ui_findings(
    comfyui: ComfyUIClient, workflow: dict[str, Any], info: dict[str, Any]
) -> tuple[
    list[RequiredNode], list[RequiredModel], list[ModelAtAnotherPath], list[RequiredInput], list[str], dict[str, str]
]:
    needs = _requirements(workflow)
    folders = await _folder_files_or_why(comfyui, [needs])
    failed = {f: why for f, why in folders.items() if isinstance(why, str)}
    listed = {f: files for f, files in folders.items() if f not in failed}
    check = _runnability(needs, info, listed)
    sources = _node_sources(workflow)
    nodes = [
        RequiredNode(
            class_type=_capped(m.class_type, DISPLAY_NAME_MAX_CHARS),
            count=m.count,
            hint=_core_hint(sources[m.class_type]),
            **sources[m.class_type],
        )
        for m in check.missing_nodes
    ]
    models = [
        RequiredModel(name=m.name, directory=m.directory, url=_text(m.url, URL_MAX_CHARS), folder_known=m.folder_known)
        for m in check.missing_models
        if m.directory not in failed
    ]
    moved = [
        _moved(m.name, _matches(m.name, listed.get(m.directory) or []), directory=m.directory)
        for m in check.models_need_value_change
    ]
    inputs = [RequiredInput(**m.model_dump()) for m in check.missing_inputs if _checkable_input(m.file)]
    notes = [
        f"the model folder {_capped(f, DISPLAY_NAME_MAX_CHARS)!r} couldn't be listed ({why}), so the models declared "
        "in it weren't checked"
        for f, why in sorted(failed.items())
    ]
    if len(inputs) < len(check.missing_inputs):
        notes.append(_input_note(len(check.missing_inputs) - len(inputs)))
    urls = {m["name"]: m["url"] for m in needs.models if isinstance(m.get("url"), str)}
    return nodes, models, moved, inputs, notes, urls


# -- API format: the graph's values ---------------------------------------------


def _api_refs(graph: dict[str, Any], info: dict[str, Any]) -> tuple[Counter[str], list[dict[str, Any]], list[tuple]]:
    """(class counts, file values not among their COMBO options, the core loaders' input files) of an API graph."""
    uses: Counter[str] = Counter()
    refs: list[dict[str, Any]] = []
    inputs: dict[tuple[str, str], tuple[str, str, str, str]] = {}
    # Each loader input's options as a set, and those that name files, worked out once however many nodes use it:
    # a folder's listing can run to tens of thousands.
    combos: dict[tuple[str, str], tuple[frozenset[Any], list[str] | None]] = {}
    for node_id, node in graph.items():
        if not isinstance(node, dict) or not isinstance(node.get("class_type"), str):
            continue
        kind = node["class_type"]
        uses[kind] += 1
        spec = info.get(kind)
        values = node.get("inputs")
        if not spec or not isinstance(values, dict):
            continue
        sections = spec.get("input", {})
        specs = {k: v for section in ("optional", "required") for k, v in (sections.get(section) or {}).items()}
        for name, value in values.items():
            if not isinstance(value, str) or not value:
                continue
            if name == INPUT_LOADERS.get(kind):
                inputs.setdefault((kind, value), (kind, name, value, str(node_id)))
                continue
            if not FILE_NAME.search(value):
                continue
            if (kind, name) not in combos:
                options = _combo_values(specs.get(name))
                # The options that name files: VAELoader's, say, add approximate decoders to its folder's files.
                combos[kind, name] = (
                    frozenset(o for o in options or () if isinstance(o, str)),
                    [o for o in options if isinstance(o, str) and FILE_NAME.search(o)] if options is not None else None,
                )
            present, files = combos[kind, name]
            if files is None or value in present:
                continue
            refs.append({"node_id": str(node_id), "class_type": kind, "input": name, "value": value, "files": files})
    return uses, refs, list(inputs.values())


# Each ComfyUI's model folder listings, once complete: (when they were read, folder -> its files as a frozenset).
_listed: weakref.WeakKeyDictionary[ComfyUIClient, tuple[float, dict[str, frozenset[str]]]] = weakref.WeakKeyDictionary()


async def _listings(comfyui: ComfyUIClient) -> dict[str, frozenset[str]]:
    """Every model folder's files, for at most MODEL_FOLDERS_SECONDS, reused for LISTINGS_TTL_SECONDS once complete.
    A folder not listed in time, or whose name is too long to name in an install path, is left out."""
    held = _listed.get(comfyui)
    if held is not None and time.monotonic() - held[0] <= LISTINGS_TTL_SECONDS:
        return held[1]
    try:
        folders = await asyncio.wait_for(comfyui.model_folders(), MODEL_FOLDERS_SECONDS)
    except (ComfyUIError, TimeoutError):
        return {}
    gate = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def files(folder: str) -> list[str]:
        async with gate:
            return await comfyui.model_files(folder)

    wanted = [f for f in folders if f not in NOT_LISTED and len(f) <= DISPLAY_NAME_MAX_CHARS]
    got = await _bounded({f: lambda f=f: files(f) for f in wanted}, MODEL_FOLDERS_SECONDS)
    listings = {f: frozenset(v) for f, v in got.items() if isinstance(v, list)}
    if len(listings) == len(wanted):
        _listed[comfyui] = (time.monotonic(), listings)
    return listings


def _folder_of(files: frozenset[str], listings: dict[str, frozenset[str]]) -> str | None:
    """The one model folder whose listing is exactly a loader's file options, as ComfyUI lists both from it."""
    if not files:
        return None  # an empty listing matches every empty folder
    matches = [f for f, listed in listings.items() if len(listed) == len(files) and listed == files]
    return matches[0] if len(matches) == 1 else None


async def _api_findings(
    comfyui: ComfyUIClient, graph: dict[str, Any], info: dict[str, Any]
) -> tuple[
    list[RequiredNode], list[RequiredModel], list[ModelAtAnotherPath], list[RequiredInput], list[str], dict[Any, list]
]:
    """The findings, notes, and each missing model's loader options by (class_type, input), for its suggestions."""
    uses, refs, loader_inputs = _api_refs(graph, info)
    nodes = [
        RequiredNode(class_type=_capped(k, DISPLAY_NAME_MAX_CHARS), count=c) for k, c in uses.items() if k not in info
    ]
    listings = await _listings(comfyui) if refs else {}
    choices: dict[Any, list[str]] = {}
    folder: dict[Any, str | None] = {}
    by_name: dict[Any, dict[str, list[str]]] = {}
    models, moved = [], []
    for ref in refs:
        # The loader input as the report names it; _scan finds its options by the same key.
        key = (_capped(ref["class_type"], DISPLAY_NAME_MAX_CHARS), _capped(ref["input"], DISPLAY_NAME_MAX_CHARS))
        if key not in folder:  # worked out once per loader input, however many nodes use it
            choices[key] = ref["files"]
            folder[key] = _folder_of(frozenset(ref["files"]), listings)
            by_name[key] = {}
            for f in ref["files"]:  # _matches, as a lookup: the value itself isn't among the options
                by_name[key].setdefault(f.rsplit("/", 1)[-1], []).append(f)
        where = {
            "directory": folder[key],
            "node_id": _capped(ref["node_id"], DISPLAY_NAME_MAX_CHARS),
            "class_type": key[0],
            "input": key[1],
        }
        found = by_name[key].get(ref["value"])
        if found:
            moved.append(_moved(ref["value"], found, **where))
        else:
            models.append(RequiredModel(name=ref["value"], **where))
    checkable = [i for i in loader_inputs if _checkable_input(i[2])]
    node_of = {(kind, value): node_id for kind, _, value, node_id in checkable}
    inputs = [
        RequiredInput(**m.model_dump(), node_id=node_of.get((m.class_type, m.file)))
        for m in _missing_inputs([i[:3] for i in checkable], info)
    ]
    notes = [_input_note(len(loader_inputs) - len(checkable))] if len(checkable) < len(loader_inputs) else []
    return nodes, models, moved, inputs, notes, choices


# -- suggestions ------------------------------------------------------------------


def _bigrams(text: str) -> frozenset[str]:
    return frozenset(text[i : i + 2] for i in range(len(text) - 1))


def _file_index(
    choices: list[str], stopped: Callable[[], bool]
) -> tuple[dict[str, list[str]], list[tuple[str, frozenset[str]]]] | None:
    """A loader's files by lowercased file name, the key _close compares, and each name's character pairs for its
    prefilter. Paths too long to use whole are left out. Built once per loader input, a chunk at a time; None when
    stopped."""
    keys: dict[str, list[str]] = {}
    for c in choices:
        if len(c) <= PATH_MAX_CHARS:
            keys.setdefault(c.rsplit("/", 1)[-1].lower(), []).append(c)
    names = list(keys)
    grams: list[tuple[str, frozenset[str]]] = []
    for i in range(0, len(names), SCAN_CHUNK):
        if stopped():
            return None
        grams += [(k, _bigrams(k)) for k in names[i : i + SCAN_CHUNK]]
    return keys, grams


def _close(
    word: str, index: tuple[dict[str, list[str]], list[tuple[str, frozenset[str]]]], stopped: Callable[[], bool]
) -> list[str] | None:
    """The MAX_SUGGESTIONS closest files by difflib's ratio between lowercased file names (cutoff 0.6), among the
    PREFILTER names sharing the most character pairs with it. difflib's ratio costs far more per name than a set
    intersection, and a folder can hold tens of thousands, so only the prefilter sees them all, a chunk at a time,
    checking for a stop between chunks. None when stopped."""
    keys, grams = index
    target = word.rsplit("/", 1)[-1].lower()
    wanted = _bigrams(target)
    best: list[tuple[int, str]] = []
    for i in range(0, len(grams), SCAN_CHUNK):
        if stopped():
            return None
        chunk = ((len(wanted & g), k) for k, g in grams[i : i + SCAN_CHUNK])
        best = heapq.nlargest(PREFILTER, [*best, *chunk])
    found = difflib.get_close_matches(target, [k for _, k in best], MAX_SUGGESTIONS, 0.6)
    return [c for k in found for c in keys[k]][:MAX_SUGGESTIONS] or None


def _scan(
    nodes: list[RequiredNode],
    models: list[RequiredModel],
    info: dict[str, Any],
    choices: dict[Any, list[str]],
    stopped: Callable[[], bool],
) -> tuple[list[list[str] | None], list[list[str] | None]]:
    """Suggestions for the first MAX_SUGGESTED of each, in order, as far as it gets before `stopped`. Classes are
    matched as node_describe matches them (_closest, over class and display names); class names too long to use
    whole are never suggested."""
    for_nodes: list[list[str] | None] = []
    index = None
    for node in nodes[:MAX_SUGGESTED]:
        if stopped():
            break
        if index is None:
            index = _name_index((k, d) for k, d in _names(info) if len(k) <= DISPLAY_NAME_MAX_CHARS)
        for_nodes.append([s["id"] for s in _closest(node.class_type, index, MAX_SUGGESTIONS)] or None)
    for_models: list[list[str] | None] = []
    indexes: dict[Any, dict[str, list[str]]] = {}  # one per loader input, however many of its values are missing
    for model in models[:MAX_SUGGESTED]:
        if stopped():
            break
        key = (model.class_type, model.input)
        if key not in indexes:
            index = _file_index(choices.get(key) or [], stopped)
            if index is None:
                break
            indexes[key] = index
        found = _close(model.name, indexes[key], stopped)
        if found is None and stopped():
            break
        for_models.append(found)
    return for_nodes, for_models


async def _suggest(
    nodes: list[RequiredNode], models: list[RequiredModel], info: dict[str, Any], choices: dict[Any, list[str]]
) -> str | None:
    """Fill in suggestions, off the event loop, for at most SUGGEST_SECONDS: the thread checks the deadline, and a
    stop flag set when this is cancelled, between chunks of work, so it never outlives the call by more than one.
    Returns a note when some were left out."""
    wanted = min(len(nodes), MAX_SUGGESTED) + min(len(models), MAX_SUGGESTED)
    if not wanted:
        return None
    stop = threading.Event()
    deadline = time.monotonic() + SUGGEST_SECONDS

    def stopped() -> bool:
        return stop.is_set() or time.monotonic() > deadline

    try:
        for_nodes, for_models = await asyncio.to_thread(_scan, nodes, models, info, choices, stopped)
    finally:
        stop.set()
    for node, names in zip(nodes, for_nodes, strict=False):
        node.suggestions = names
    for model, names in zip(models, for_models, strict=False):
        model.suggestions = names
    if len(for_nodes) + len(for_models) < wanted:
        return f"suggestions stopped after {SUGGEST_SECONDS:g}s; the entries after that have none"
    if len(nodes) > MAX_SUGGESTED or len(models) > MAX_SUGGESTED:
        return f"suggestions are given for the first {MAX_SUGGESTED} missing classes and models only"
    return None


# -- proposals ------------------------------------------------------------------

PROPOSAL_NOTE = (
    "Proposals only, for a human or deployer to review and apply; nothing here installs or downloads. "
    "comfy_yaml_models are entries for the deployment's comfy.yaml (then regenerate the lock with comfyctl fetch "
    "resolve). custom_nodes is an entry for comfy-lock.yaml's custom_nodes section, in ComfyUI-Manager's snapshot "
    "shape: add it to the section's existing maps, and fill in any <...> value. The comfyui-workflows guide "
    "models-and-nodes has the rules."
)


def _model_entry(model: RequiredModel, url: str | None, notes: list[str]) -> dict[str, Any] | None:
    """A comfy.yaml entry for a missing model, from the full URL the graph gives (never the capped one shown)."""
    if not (url and model.directory):
        return None
    if model.folder_known is False:
        notes.append(
            f"no comfy.yaml entry is proposed for {model.name!r}: this ComfyUI has no {model.directory!r} model "
            "folder type, so no loader would offer it"
        )
        return None
    parts = urlsplit(url)
    if parts.scheme != "https":
        return None
    entry: dict[str, Any] = {"install": f"models/{model.directory}/"}
    hf = HF_URL.match(parts.path) if parts.netloc == "huggingface.co" else None
    civitai = CIVITAI_URL.match(parts.path) if parts.netloc == "civitai.com" else None
    if hf:
        repo, revision, path = (unquote(g) for g in hf.groups())
        entry = {"source": f"hf:{repo}", "file": path, **entry}
        if revision != "main":
            entry["revision"] = revision
        if path.rsplit("/", 1)[-1] != model.name:
            entry["as"] = model.name
    elif civitai:
        entry = {"source": f"civitai:{civitai.group(1)}", "as": model.name, **entry}
    else:
        entry = {"source": url, "sha256": "<the file's SHA256>", "as": model.name, **entry}
    if any(isinstance(v, str) and len(v) > URL_MAX_CHARS for v in entry.values()):
        return None  # a URL or path too long to give whole is not proposed in part
    stem = model.name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return {"name": stem.lower(), "files": [entry]}


def _pack_entries(nodes: list[RequiredNode]) -> dict[str, Any] | None:
    """A registry pack (cnr_id) pinned to its released version, or a git pack (aux_id, a GitHub owner/repo) pinned
    to its commit. A version the node doesn't name, or that can't be pinned, is left as a <...> to fill in."""
    git: dict[str, Any] = {}
    cnr: dict[str, str] = {}
    for node in nodes:
        version = node.version or ""
        sha = bool(GIT_SHA.match(version))
        release = bool(version) and not sha and version not in UNPINNED_VERSIONS
        pack = node.pack if node.pack != CORE_PACK else None
        if pack and (release or not node.aux_id):
            cnr.setdefault(pack, version if release else "<a released version>")
        elif node.aux_id:
            commit = version if sha else "<a full commit SHA>"
            git.setdefault(f"https://github.com/{node.aux_id}", {"disabled": False, "hash": commit})
    if not (git or cnr):
        return None
    return {"git_custom_nodes": git, **({"cnr_custom_nodes": cnr} if cnr else {})}


def _proposals(
    nodes: list[RequiredNode], models: list[RequiredModel], urls: dict[str, str], notes: list[str]
) -> Proposals | None:
    entries = [e for e in (_model_entry(m, urls.get(m.name), notes) for m in models) if e is not None]
    packs = _pack_entries(nodes)
    if not (entries or packs):
        return None
    return Proposals(note=PROPOSAL_NOTE, comfy_yaml_models=entries or None, custom_nodes=packs)


# -- the report -----------------------------------------------------------------

UNCONVERTED_NOTE = (
    "a UI graph this server didn't convert is read from its nodes' properties alone: models named only in widget "
    "values weren't checked, so satisfied is never true here. The mcp-convert image checks those too"
)


def _capped_list(items: list[Any]) -> tuple[list[Any], bool]:
    return items[:MAX_ITEMS], len(items) > MAX_ITEMS


async def _report(
    comfyui: ComfyUIClient, given: dict[str, Any], api_graph: dict[str, Any] | None, info: dict[str, Any], ui: bool
) -> WorkflowRequirements:
    info = _tolerant(info)
    nodes, models, moved, inputs, notes, urls, choices = [], [], [], [], [], {}, {}
    if ui:
        nodes, models, moved, inputs, notes, urls = await _ui_findings(comfyui, given, info)
    if api_graph is not None:
        api_nodes, api_models, api_moved, api_inputs, api_notes, choices = await _api_findings(comfyui, api_graph, info)
        named: set[str] = set()
        if ui:  # the UI graph's own findings stand; its widget values add only models it didn't declare
            named = {m.name for m in (*models, *moved)} | {m["name"] for m in _requirements(given).models}
        else:
            nodes = api_nodes
        models += [m for m in api_models if m.name not in named]
        moved += [m for m in api_moved if m.name not in named]
        seen = {(i.class_type, i.file) for i in inputs}
        inputs += [i for i in api_inputs if (i.class_type, i.file) not in seen]
        notes += [n for n in api_notes if n not in notes]
    lists = [_capped_list(x) for x in (nodes, models, moved, inputs)]
    (nodes, cut1), (models, cut2), (moved, cut3), (inputs, cut4) = lists
    # Every note so far says something wasn't checked: a folder that couldn't be listed, input values the loader
    # resolves itself. The ones added below (proposals, suggestions) don't.
    unchecked = bool(notes)
    proposals = _proposals(nodes, models, urls, notes)  # of the capped lists, so each map is capped too
    note = await _suggest(nodes, models, info, choices)
    if note:
        notes.append(note)
    if ui and api_graph is None:
        notes.append(UNCONVERTED_NOTE)
        unchecked = True
    satisfied: bool | None = not (nodes or models or moved or inputs)
    if unchecked:
        satisfied = satisfied and None  # nothing listed is not everything checked: null, never true
    return WorkflowRequirements(
        format="ui" if ui else "api",
        satisfied=satisfied,
        missing_nodes=nodes,
        missing_models=models,
        models_need_value_change=moved,
        missing_inputs=inputs,
        truncated=True if (cut1 or cut2 or cut3 or cut4) else None,
        notes=notes or None,
        proposals=proposals,
    )


async def workflow_requirements(
    comfyui: ComfyUIClient,
    given: dict[str, Any],
    api_graph: dict[str, Any] | None,
    info: dict[str, Any],
    ui: bool,
) -> tuple[WorkflowRequirements | None, str | None]:
    """(the report, None), or (None, why there is none): `timeout`, an error code, or `check_failed`.

    `given` is the graph as the agent sent it; `ui` says it is the UI format. `api_graph` is the API graph to read
    values from: the one given, or the one this server converted a UI graph to; None when there is none. `info` is
    the /object_info the validation used."""
    try:
        report = await asyncio.wait_for(_report(comfyui, given, api_graph, info, ui), REQUIREMENTS_SECONDS)
    except TimeoutError:
        return None, "timeout"
    except RelayError as exc:
        return None, exc.code
    except Exception:  # optional detail: a shape no check expects is its own answer, not the call's failure
        log.exception("workflow_validate: the requirements report failed")
        return None, "check_failed"
    return report, None
