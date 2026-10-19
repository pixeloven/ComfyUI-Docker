"""The user's saved workflows (#216): the files the editor's workflows sidebar lists and opens.

    workflow_list_saved   read   GET /api/userdata?dir=workflows&recurse=true&full_info=true
    workflow_get_saved    read   GET /api/userdata/workflows%2F<name>
    workflow_save         run    POST /api/userdata/workflows%2F<name>?overwrite=...

They are ComfyUI's own userdata routes, which the editor uses, for the default user's `workflows` folder
(user/default/workflows): nothing here touches a filesystem. workflow_validate and workflow_run also take a saved
workflow by name (`saved`), through read_saved below, so a run needn't carry the graph.

Names. A name is a path relative to the workflows folder, as workflow_list_saved gives it, ending in `.json`. It is
checked here before any request (saved_name): no absolute path, no `..` or `.` segment, no empty segment, no
backslash, no control character, no `%` (ComfyUI decodes a name that holds one a second time), no segment starting
with a dot (ComfyUI's listing skips those, so the sidebar would never show the file), at most MAX_NAME_CHARS. A
leading `workflows/` is dropped, since agents name the folder too. ComfyUI also keeps every path inside the user's
directory itself (403 otherwise).

Format (the owner's question on #216, measured on frontend 1.53.6). The sidebar opens a file through
app.loadGraphData, which reads `nodes` and `links`: an API-format file opens as an empty canvas, with only a
console warning, and saving that tab writes the empty graph back. So workflow_save takes the UI format only and
refuses an API graph (`api_format_not_saved`). It is written as the editor writes it, JSON.stringify's compact
form, so a workflow read and saved unchanged is the same bytes; with overwrite, a save whose content the file
already holds isn't written at all, which keeps a file another tool formatted byte for byte.

Overwrite (owner decision on #216). A save onto an existing name is refused unless `overwrite: true`; ComfyUI makes
that check itself (overwrite=false, HTTP 409), so there is no window between a check and the write.

Caps: MAX_SAVED_BYTES on what is read or written, MAX_LISTED names in a listing, and WORKFLOW_MAX_CHARS on the
workflow workflow_get_saved returns (as template_get). Everything ComfyUI returns is untrusted: listed names that
fail saved_name are counted, not shown.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import unicodedata
from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated, Any, Literal

from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from .comfyui import ComfyUIError
from .convert import is_ui_format
from .errors import RelayError
from .tools_introspection import READ, READ_ONLY, WORKFLOW_MAX_CHARS, workflow_chars

if TYPE_CHECKING:
    from .tools import Relay

FOLDER = "workflows"
# The most a saved workflow may be, read or written: about 25 times the largest template that fits
# WORKFLOW_MAX_CHARS, and well under the HTTP transport's request limit.
MAX_SAVED_BYTES = 2 * 1024 * 1024
# The most names a listing returns, newest first.
MAX_LISTED = 200
MAX_NAME_CHARS = 255
# Close names for an unknown one are optional detail: their listing gets this long.
SUGGEST_SECONDS = 3.0

SavedName = Annotated[
    str,
    Field(description="As workflow_list_saved gives it: a path in the user's workflows folder, ending in .json"),
]


def invalid_name(name: str, why: str, **detail: Any) -> RelayError:
    return RelayError("invalid_workflow_name", f"{name[:300]!r} isn't a saved workflow name: {why}", **detail)


def saved_name(name: str) -> str:
    """The name, checked, relative to the workflows folder; RelayError `invalid_workflow_name` otherwise."""
    if name.startswith(f"{FOLDER}/"):
        name = name[len(FOLDER) + 1 :]
    if not name:
        raise invalid_name(name, "it is empty")
    if len(name) > MAX_NAME_CHARS:
        raise invalid_name(name, f"it is {len(name)} characters, over {MAX_NAME_CHARS}")
    for ch in name:
        if unicodedata.category(ch) in ("Cc", "Cs", "Zl", "Zp"):
            raise invalid_name(name, f"it holds a control character (U+{ord(ch):04X})")
    if "\\" in name:
        raise invalid_name(name, "it holds a backslash; separate folders with /")
    if "%" in name:
        raise invalid_name(name, "it holds %, which ComfyUI would decode as an escape")
    if name.startswith("/"):
        raise invalid_name(name, "it is an absolute path; give it relative to the workflows folder")
    for segment in name.split("/"):
        if segment in ("", ".", ".."):
            raise invalid_name(name, "every folder in it must be named, and none may be . or ..")
        if segment.startswith("."):
            raise invalid_name(name, f"{segment!r} starts with a dot, so the editor's sidebar would never list it")
        if len(segment.encode()) > 255:
            raise invalid_name(name, f"{segment[:40]!r}... is over 255 bytes, too long for a file name")
    if not name.endswith(".json"):
        raise invalid_name(name, "saved workflows end in .json", expected=f"{name}.json")
    return name


def userdata_path(name: str) -> str:
    return f"{FOLDER}/{name}"


def workflow_format(workflow: Any) -> Literal["ui", "api", "unknown"]:
    if is_ui_format(workflow):
        return "ui"
    if (
        isinstance(workflow, dict)
        and workflow
        and all(isinstance(n, dict) and isinstance(n.get("class_type"), str) for n in workflow.values())
    ):
        return "api"
    return "unknown"


async def _suggestions(relay: Relay, name: str) -> list[str]:
    """Saved names close to an unknown one: optional, so any failure or a slow listing gives none."""
    try:
        listed = await asyncio.wait_for(relay.comfyui.userdata_list(FOLDER), SUGGEST_SECONDS)
    except Exception:  # noqa: BLE001 -- detail for an error already being raised; never its own failure
        return []
    names = [f["path"] for f in listed or [] if str(f["path"]).endswith(".json")][: MAX_LISTED * 5]
    return difflib.get_close_matches(name, names, n=5, cutoff=0.5)


async def read_saved(relay: Relay, name: str) -> tuple[str, dict[str, Any], int]:
    """(checked name, the workflow, its size in bytes): a saved workflow read through ComfyUI, which must be a JSON
    object. `unknown_saved_workflow` when there is none by that name."""
    name = saved_name(name)
    body = await relay.comfyui.userdata_read(userdata_path(name), MAX_SAVED_BYTES)
    if body is None:
        raise RelayError(
            "unknown_saved_workflow",
            f"the user has no saved workflow {name!r}; workflow_list_saved lists them",
            suggestions=await _suggestions(relay, name),
        )
    try:
        workflow = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        workflow = None
    if not isinstance(workflow, dict):
        raise RelayError(
            "invalid_saved_workflow", f"{name} isn't a workflow: its content isn't a JSON object", name=name
        )
    return name, workflow, len(body)


def editor_json(workflow: dict[str, Any]) -> bytes:
    """The workflow as the editor writes a saved one: JSON.stringify's compact form, UTF-8."""
    try:
        return json.dumps(workflow, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (UnicodeEncodeError, ValueError) as exc:
        raise RelayError("invalid_workflow", f"the workflow can't be written as JSON: {exc}") from None


# -- workflow_list_saved --------------------------------------------------------


class SavedEntry(BaseModel):
    name: str
    size_bytes: int | None
    modified: float | None = Field(description="Unix seconds")


class SavedList(BaseModel):
    folder: str = Field(description="Where they live: ComfyUI's user/default/workflows")
    total: int = Field(description="Saved workflows (.json files) ComfyUI has there")
    workflows: list[SavedEntry] = Field(description=f"Newest first, at most {MAX_LISTED}")
    omitted: int = Field(description=f"How many more there are past the first {MAX_LISTED}")
    unaddressable: int = Field(
        default=0, description="Files there whose names these tools refuse (a dot, %, ...), left out of total"
    )


def _workflow_list_saved(relay: Relay) -> Callable[..., Any]:
    async def workflow_list_saved() -> SavedList:
        """List the user's saved workflows: the files the editor's workflows sidebar shows (ComfyUI's
        user/default/workflows), newest first, with size and modification time. Changes nothing.

        Read one with workflow_get_saved; workflow_validate and workflow_run also take one by name (saved).
        """
        files = await relay.comfyui.userdata_list(FOLDER) or []
        entries, bad = [], 0
        for f in files:
            path = f["path"]
            if not path.endswith(".json"):
                continue
            try:
                saved_name(path)
            except RelayError:
                bad += 1
                continue
            size, modified = f.get("size"), f.get("modified")
            entries.append(
                SavedEntry(
                    name=path,
                    size_bytes=size if isinstance(size, int) else None,
                    modified=modified / 1000 if isinstance(modified, (int, float)) else None,
                )
            )
        entries.sort(key=lambda e: e.modified or 0, reverse=True)
        return SavedList(
            folder=f"user/default/{FOLDER}",
            total=len(entries),
            workflows=entries[:MAX_LISTED],
            omitted=max(0, len(entries) - MAX_LISTED),
            unaddressable=bad,
        )

    return workflow_list_saved


# -- workflow_get_saved ---------------------------------------------------------


class SavedWorkflow(BaseModel):
    name: str
    format: Literal["ui", "api", "unknown"] = Field(
        description="ui: the editor's format (nodes, links), which it opens. api: a /prompt graph, which the "
        "editor's sidebar opens as an empty canvas. unknown: neither"
    )
    size_bytes: int
    workflow: dict[str, Any]


def _workflow_get_saved(relay: Relay) -> Callable[..., Any]:
    async def workflow_get_saved(name: SavedName) -> SavedWorkflow:
        """Read one of the user's saved workflows, as the editor stores it. Changes nothing.

        The editor saves UI format: nodes with widgets_values (in widget order), links, subgraph definitions. To
        change it, edit values in place, keep the rest, and save it back with workflow_save(overwrite=true); to run
        it, workflow_run(saved=name). Over 80,000 characters as JSON fails with workflow_too_large; an unknown name
        with unknown_saved_workflow and close names.
        """
        checked, workflow, size = await read_saved(relay, name)
        chars = workflow_chars(workflow)
        if chars > WORKFLOW_MAX_CHARS:
            raise RelayError(
                "workflow_too_large",
                f"{checked} is {chars} characters as JSON, over the {WORKFLOW_MAX_CHARS} this tool returns: most MCP "
                "clients cut a result that long. workflow_validate and workflow_run still take it by name (saved).",
                size=chars,
                limit=WORKFLOW_MAX_CHARS,
            )
        return SavedWorkflow(name=checked, format=workflow_format(workflow), size_bytes=size, workflow=workflow)

    return workflow_get_saved


# -- workflow_save ----------------------------------------------------------------


class SavedResult(BaseModel):
    name: str
    written: bool = Field(description="false: the file already held exactly this workflow, so it was left as it was")
    replaced: bool = Field(description="An existing file by this name was replaced (overwrite: true)")
    size_bytes: int


def _workflow_save(relay: Relay) -> Callable[..., Any]:
    async def workflow_save(
        name: SavedName,
        workflow: Annotated[
            dict[str, Any],
            Field(description="UI format (nodes, links), as workflow_get_saved or template_get returns it"),
        ],
        overwrite: bool = Field(
            default=False, description="true replaces a saved workflow of this name; otherwise that is refused"
        ),
    ) -> SavedResult:
        """Save a workflow to the user's workflows, where the editor's sidebar lists and opens it.

        UI format only: the editor opens an API-format file as an empty canvas, so that is refused
        (api_format_not_saved). Written as the editor writes it: read and saved unchanged, it is the same bytes. An
        existing name is refused with workflow_exists unless overwrite is true. Not validated: use
        workflow_validate(saved=name). An editor tab already open keeps its copy until reopened.
        """
        name = saved_name(name)
        kind = workflow_format(workflow)
        if kind == "api":
            raise RelayError(
                "api_format_not_saved",
                "refused: this is an API-format graph, and the editor's workflows sidebar opens a saved API-format "
                "file as an empty canvas. Save the UI-format workflow (nodes, links) that workflow_get_saved or "
                "template_get returned, with your changes made in it. Nothing was written.",
            )
        if kind != "ui":
            raise RelayError(
                "invalid_workflow",
                'not a UI-format workflow: it needs "nodes" and "links" lists, as workflow_get_saved and '
                "template_get return them. Nothing was written.",
            )
        body = editor_json(workflow)
        if len(body) > MAX_SAVED_BYTES:
            raise RelayError(
                "saved_workflow_too_large",
                f"the workflow is {len(body)} bytes as JSON, over the {MAX_SAVED_BYTES} this server writes",
                limit=MAX_SAVED_BYTES,
                size_bytes=len(body),
            )
        path = userdata_path(name)
        replaced = False
        if overwrite:
            try:
                held = await relay.comfyui.userdata_read(path, MAX_SAVED_BYTES)
            except ComfyUIError as exc:
                if exc.code != "saved_workflow_too_large":
                    raise
                held = b""  # larger than anything written here: it differs
            if held is not None:
                replaced = True
                try:
                    same = editor_json(json.loads(held.decode("utf-8"))) == body
                except (UnicodeDecodeError, ValueError, RelayError, TypeError):
                    same = False
                if same:
                    return SavedResult(name=name, written=False, replaced=False, size_bytes=len(held))
        written = await relay.comfyui.userdata_write(path, body, overwrite=overwrite)
        size = written.get("size")
        return SavedResult(
            name=name, written=True, replaced=replaced, size_bytes=size if isinstance(size, int) else len(body)
        )

    return workflow_save


# -- registration ---------------------------------------------------------------

RUN = frozenset({"run"})

# workflow_save is destructive with overwrite (it replaces a file), and idempotent: the same workflow under the same
# name leaves the same file.
SAVED_TOOLS: tuple[tuple[str, frozenset[str], Callable[[Relay], Callable[..., Any]], ToolAnnotations], ...] = (
    ("workflow_list_saved", READ, _workflow_list_saved, READ_ONLY),
    ("workflow_get_saved", READ, _workflow_get_saved, READ_ONLY),
    (
        "workflow_save",
        RUN,
        _workflow_save,
        ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False),
    ),
)
