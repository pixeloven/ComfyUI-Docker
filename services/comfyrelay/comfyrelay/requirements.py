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

A UI graph this server converted is read both ways, so a model named only in a widget value is found too.

It only reports. Values and types are ComfyUI's to check at /prompt (#145), and nothing here installs or downloads:
the proposals are for a human or deployer to review and apply (#201, D1). Everything it says comes from the graph
it was given and from ComfyUI's own data, both capped. It is optional detail on workflow_validate, so it has a
total time bound, and a failure leaves it out and says why (requirements_unchecked) without failing the call.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import Field

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
    _on_disk,
    _requirements,
    _runnability,
)

log = logging.getLogger("comfyrelay")

# The whole report gets this long, its model folder listings included; then it is left out (`timeout`).
REQUIREMENTS_SECONDS = 10.0
# Each list keeps at most this many entries (truncated says so), each suggestion list this many names.
MAX_ITEMS = 50
MAX_SUGGESTIONS = 3
# Strings from the graph's own properties (a pack id, a version, a URL) are cut to this width.
FIELD_MAX_CHARS = 200
URL_MAX_CHARS = 500
# A COMBO value that names a file: an extension that starts with a letter, so "v1.5" or "1.0" are not files.
FILE_NAME = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,11}$")
# A full git commit SHA, and the registry versions ComfyUI-Manager never pins (get_current_snapshot).
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
UNPINNED_VERSIONS = frozenset({"nightly", "latest", "unknown"})
# ComfyUI's own nodes carry this cnr_id: a missing one needs a newer ComfyUI, not a node pack.
CORE_PACK = "comfy-core"
HF_URL = re.compile(r"^https://huggingface\.co/([^/]+/[^/]+)/(?:resolve|blob)/([^/]+)/(.+)$")


class RequiredNode(_Compact):
    class_type: str
    count: int = Field(description="How many nodes of it the graph has")
    pack: str | None = Field(default=None, description="UI format: the registry pack (cnr_id) the node names")
    aux_id: str | None = Field(default=None, description="UI format: the git repository (owner/repo) the node names")
    version: str | None = Field(default=None, description="UI format: the pack version or commit the node names (ver)")
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


class WorkflowRequirements(_Compact):
    format: Literal["ui", "api"] = Field(description="How it was read: ui (node properties), api (input values)")
    satisfied: bool = Field(description="Nothing below is missing. It says nothing about values or types")
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


async def _ui_findings(
    comfyui: ComfyUIClient, workflow: dict[str, Any], info: dict[str, Any]
) -> tuple[list[RequiredNode], list[RequiredModel], list[ModelAtAnotherPath], list[RequiredInput], list[str]]:
    needs = _requirements(workflow)
    folders = await _folder_files_or_why(comfyui, [needs])
    failed = {f: why for f, why in folders.items() if isinstance(why, str)}
    check = _runnability(needs, info, {f: files for f, files in folders.items() if f not in failed})
    sources = _node_sources(workflow)
    nodes = [
        RequiredNode(class_type=_capped(m.class_type, DISPLAY_NAME_MAX_CHARS), count=m.count, **sources[m.class_type])
        for m in check.missing_nodes
    ]
    models = [
        RequiredModel(name=m.name, directory=m.directory, url=_text(m.url, URL_MAX_CHARS), folder_known=m.folder_known)
        for m in check.missing_models
        if m.directory not in failed
    ]
    moved = [ModelAtAnotherPath(**m.model_dump()) for m in check.models_need_value_change]
    inputs = [RequiredInput(**m.model_dump()) for m in check.missing_inputs]
    notes = [
        f"the model folder {_capped(f, DISPLAY_NAME_MAX_CHARS)!r} couldn't be listed ({why}), so the models declared "
        "in it weren't checked"
        for f, why in sorted(failed.items())
    ]
    return nodes, models, moved, inputs, notes


# -- API format: the graph's values ---------------------------------------------


def _api_refs(graph: dict[str, Any], info: dict[str, Any]) -> tuple[Counter[str], list[dict[str, Any]], list[tuple]]:
    """(class counts, file values not among their COMBO options, the core loaders' input files) of an API graph."""
    uses: Counter[str] = Counter()
    refs: list[dict[str, Any]] = []
    inputs: dict[tuple[str, str], tuple[str, str, str, str]] = {}
    for node_id, node in graph.items():
        if not isinstance(node, dict) or not isinstance(node.get("class_type"), str):
            continue
        kind = node["class_type"]
        uses[kind] += 1
        spec = info.get(kind)
        values = node.get("inputs")
        if not isinstance(spec, dict) or not isinstance(values, dict):
            continue
        sections = spec.get("input") if isinstance(spec.get("input"), dict) else {}
        specs = {
            k: v
            for section in ("optional", "required")
            if isinstance(sections.get(section), dict)
            for k, v in sections[section].items()
        }
        for name, value in values.items():
            if not isinstance(value, str) or not value:
                continue
            if name == INPUT_LOADERS.get(kind):
                inputs.setdefault((kind, value), (kind, name, value, str(node_id)))
                continue
            options = _combo_values(specs.get(name))
            if options is None or value in options or not FILE_NAME.search(value):
                continue
            # The options that name files: VAELoader's, say, add names of approximate decoders to its folder's files.
            files = [o for o in options if isinstance(o, str) and FILE_NAME.search(o)]
            refs.append({"node_id": str(node_id), "class_type": kind, "input": name, "value": value, "files": files})
    return uses, refs, list(inputs.values())


async def _listings(comfyui: ComfyUIClient) -> dict[str, list[str]]:
    """Every model folder's files, for at most MODEL_FOLDERS_SECONDS; a folder not listed in time is left out."""
    try:
        folders = await asyncio.wait_for(comfyui.model_folders(), MODEL_FOLDERS_SECONDS)
    except (ComfyUIError, TimeoutError):
        return {}
    gate = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def files(folder: str) -> list[str]:
        async with gate:
            return await comfyui.model_files(folder)

    wanted = [f for f in folders if f not in NOT_MODEL_FOLDERS | DOT_SEGMENTS]
    got = await _bounded({f: lambda f=f: files(f) for f in wanted}, MODEL_FOLDERS_SECONDS)
    return {f: v for f, v in got.items() if isinstance(v, list)}


def _folder_of(files: list[str], listings: dict[str, list[str]]) -> str | None:
    """The one model folder whose listing is exactly a loader's file options, as ComfyUI lists both from it."""
    if not files:
        return None  # an empty listing matches every empty folder
    matches = [f for f, listed in listings.items() if set(listed) == set(files)]
    return _capped(matches[0], DISPLAY_NAME_MAX_CHARS) if len(matches) == 1 else None


async def _suggest_files(models: list[RequiredModel], choices: list[list[str]]) -> None:
    """Close names for each missing model among its loader's files (`choices`, in the same order), by the fuzzy
    match node_describe's suggestions use: scanned off the event loop, since a model folder can hold thousands of
    files, for at most SUGGEST_SECONDS, and left out past that."""
    if not models:
        return

    def scan() -> list[list[str]]:
        return [
            [s["id"] for s in _closest(m.name, _name_index((c, c) for c in files), MAX_SUGGESTIONS)]
            for m, files in zip(models, choices, strict=True)
        ]

    try:
        found = await asyncio.wait_for(asyncio.to_thread(scan), SUGGEST_SECONDS)
    except TimeoutError:
        return
    for model, names in zip(models, found, strict=True):
        model.suggestions = [_capped(s, DISPLAY_NAME_MAX_CHARS) for s in names] or None


async def _api_findings(
    comfyui: ComfyUIClient, graph: dict[str, Any], info: dict[str, Any]
) -> tuple[list[RequiredNode], list[RequiredModel], list[ModelAtAnotherPath], list[RequiredInput]]:
    uses, refs, loader_inputs = _api_refs(graph, info)
    nodes = [
        RequiredNode(class_type=_capped(k, DISPLAY_NAME_MAX_CHARS), count=c) for k, c in uses.items() if k not in info
    ]
    listings = await _listings(comfyui) if refs else {}
    models, moved = [], []
    for ref in refs:
        where = {
            "directory": _folder_of(ref["files"], listings),
            "node_id": _capped(ref["node_id"], DISPLAY_NAME_MAX_CHARS),
            "class_type": ref["class_type"],
            "input": _capped(ref["input"], DISPLAY_NAME_MAX_CHARS),
        }
        found = _on_disk(ref["value"], ref["files"])
        if found is not None:
            moved.append(
                ModelAtAnotherPath(
                    name=ref["value"],
                    found_at=found,
                    needs_value_change=f"set the loader's value from {ref['value']!r} to {found!r}",
                    **where,
                )
            )
        else:
            models.append(RequiredModel(name=ref["value"], **where))
    await _suggest_files(models, [r["files"] for r in refs if _on_disk(r["value"], r["files"]) is None])
    node_of = {(kind, value): node_id for kind, _, value, node_id in loader_inputs}
    inputs = [
        RequiredInput(**m.model_dump(), node_id=node_of.get((m.class_type, m.file)))
        for m in _missing_inputs([i[:3] for i in loader_inputs], info)
    ]
    return nodes, models, moved, inputs


# -- proposals ------------------------------------------------------------------

PROPOSAL_NOTE = (
    "Proposals only, for a human or deployer to review and apply; nothing here installs or downloads. "
    "comfy_yaml_models are entries for the deployment's comfy.yaml (then regenerate the lock with comfyctl fetch "
    "resolve). custom_nodes is an entry for comfy-lock.yaml's custom_nodes section, in ComfyUI-Manager's snapshot "
    "shape: add it to the section's existing maps, and fill in any <...> value. The comfyui-workflows guide "
    "models-and-nodes has the rules."
)


def _model_entry(model: RequiredModel) -> dict[str, Any] | None:
    if not (model.url and model.directory):
        return None
    stem = model.name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    entry: dict[str, Any] = {"install": f"models/{model.directory}/"}
    hf = HF_URL.match(model.url.split("?", 1)[0])
    if hf:
        repo, revision, path = hf.groups()
        entry = {"source": f"hf:{repo}", "file": path, **entry}
        if revision != "main":
            entry["revision"] = revision
        if path.rsplit("/", 1)[-1] != model.name:
            entry["as"] = model.name
    elif urlsplit(model.url).scheme == "https":
        entry = {"source": model.url, "sha256": "<the file's SHA256>", "as": model.name, **entry}
    else:
        return None
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


def _proposals(nodes: list[RequiredNode], models: list[RequiredModel]) -> Proposals | None:
    entries = [e for e in (_model_entry(m) for m in models) if e is not None]
    packs = _pack_entries(nodes)
    if not (entries or packs):
        return None
    return Proposals(note=PROPOSAL_NOTE, comfy_yaml_models=entries or None, custom_nodes=packs)


# -- the report -----------------------------------------------------------------


async def _suggest_classes(nodes: list[RequiredNode], info: dict[str, Any]) -> None:
    """Close class names for each missing class, as node_describe suggests them: scanned off the event loop, for at
    most SUGGEST_SECONDS, and left out past that."""
    if not nodes:
        return

    def scan() -> list[list[str]]:
        index = _name_index(_names(info))
        return [[s["id"] for s in _closest(n.class_type, index, MAX_SUGGESTIONS)] for n in nodes]

    try:
        found = await asyncio.wait_for(asyncio.to_thread(scan), SUGGEST_SECONDS)
    except TimeoutError:
        return
    for node, names in zip(nodes, found, strict=True):
        node.suggestions = [_capped(s, DISPLAY_NAME_MAX_CHARS) for s in names] or None


def _capped_list(items: list[Any]) -> tuple[list[Any], bool]:
    return items[:MAX_ITEMS], len(items) > MAX_ITEMS


async def _report(
    comfyui: ComfyUIClient, given: dict[str, Any], api_graph: dict[str, Any] | None, info: dict[str, Any], ui: bool
) -> WorkflowRequirements:
    nodes, models, moved, inputs, notes = [], [], [], [], []
    if ui:
        nodes, models, moved, inputs, notes = await _ui_findings(comfyui, given, info)
    if api_graph is not None:
        api_nodes, api_models, api_moved, api_inputs = await _api_findings(comfyui, api_graph, info)
        named: set[str] = set()
        if ui:  # the UI graph's own findings stand; its widget values add only models it didn't declare
            named = {m.name for m in (*models, *moved)} | {m["name"] for m in _requirements(given).models}
        else:
            nodes = api_nodes
        models += [m for m in api_models if m.name not in named]
        moved += [m for m in api_moved if m.name not in named]
        seen = {(i.class_type, i.file) for i in inputs}
        inputs += [i for i in api_inputs if (i.class_type, i.file) not in seen]
    proposals = _proposals(nodes, models)
    lists = [_capped_list(x) for x in (nodes, models, moved, inputs)]
    (nodes, cut1), (models, cut2), (moved, cut3), (inputs, cut4) = lists
    await _suggest_classes(nodes, info)
    return WorkflowRequirements(
        format="ui" if ui else "api",
        satisfied=not (nodes or models or moved or inputs),
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
    values from: the one given, or the one this server converted a UI graph to; None when there is none."""
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
