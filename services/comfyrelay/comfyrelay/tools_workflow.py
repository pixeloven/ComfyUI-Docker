"""The workflow tools (#132), all in the `run` profile.

    workflow_validate      type-check a graph against the live /object_info
    workflow_run           submit it; returns a job id at once (follow it with job_status)
    workflow_outputs       a finished run's files, and one file's bytes on request
    workflow_upload_input  put a file into ComfyUI's input directory

A run is a job (jobs.py). Its producer submits the graph to ComfyUI's /prompt
with a prompt id of its own making, follows it through /queue and
/history/<id>, and maps how it ended into the job's result or structured
error. Cancelled, it removes the prompt from ComfyUI's queue, or interrupts it
if it is the prompt running, before it re-raises: the producer contract in
jobs.py, inside its 3s budget. That includes a stopping server, which cancels
every job, so a relay that stops takes its runs with it: they could not be
followed or collected afterwards anyway.

Must-never (#103): a graph with a partner-API node is refused before anything
is submitted, and nothing here talks to anything but COMFYUI_URL. The only
thing written is ComfyUI's input directory, through its own upload API.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import mimetypes
import re
import time
import unicodedata
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import urlencode

from mcp_types import AudioContent, CallToolResult, ImageContent, TextContent, ToolAnnotations
from pydantic import BaseModel, Field

from .comfyui import ComfyUIClient
from .errors import RelayError
from .workflow import Problem, Report, validate

if TYPE_CHECKING:
    from .tools import Relay

log = logging.getLogger("comfyrelay.workflow")

RUN_KIND = "workflow.run"
# How often a run asks ComfyUI where its prompt is.
POLL_SECONDS = 0.5
# How long a run rides out ComfyUI not answering before the job fails.
UNREACHABLE_GRACE_SECONDS = 60.0
# Polls that find the prompt neither queued, running nor in the history before
# the run is declared lost. ComfyUI moves a prompt from running to history
# in one step under its queue lock (PromptQueue.task_done, v0.37.0), so one
# such poll is already conclusive; three rides out a proxy blip.
VANISHED_POLLS = 3
# The whole unwind after a cancel: the producer contract's 3s, less a margin.
STOP_BUDGET_SECONDS = 2.5
# How long workflow_run waits for ComfyUI to accept the graph before it
# returns the job id anyway.
SUBMIT_WAIT_SECONDS = 30.0
# Uploads arrive base64-encoded inside one MCP message.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# The most workflow_outputs returns inline, and how many files it sizes.
MAX_INLINE_BYTES = 5 * 1024 * 1024
MAX_SIZED_FILES = 32
MAX_FILENAME_CHARS = 120


# -- workflow_validate --------------------------------------------------------


class WorkflowProblem(BaseModel):
    type: str = Field(description="ComfyUI's own error type where it has one, e.g. return_type_mismatch")
    message: str
    node_id: str | None = None
    class_type: str | None = None
    input: str | None = None
    details: str | None = None
    expected: Any = Field(default=None, description="What the input takes: a type, the options, a min or max")
    got: Any = Field(default=None, description="What the graph gave it")


class PartnerApiNode(BaseModel):
    node_id: str
    class_type: str
    category: str | None = None
    signals: list[str] = Field(
        description="api_node: /object_info marks it a partner-API node. comfy_org_credentials: it asks for the "
        "user's Comfy.org credentials, which pay for partner-API calls"
    )


class ValidationResult(BaseModel):
    valid: bool = Field(description="No errors. Warnings do not stop a run")
    runnable: bool = Field(description="Valid, and no partner-API nodes: workflow_run would submit it")
    errors: list[WorkflowProblem]
    warnings: list[WorkflowProblem]
    partner_api_nodes: list[PartnerApiNode] = Field(description="workflow_run refuses a graph with any")
    output_nodes: list[str] = Field(description="Node ids ComfyUI would run the graph for")
    node_count: int


WorkflowArg = Annotated[
    dict[str, Any],
    Field(
        description='The workflow in ComfyUI\'s API format: {"<node id>": {"class_type": "<node class>", '
        '"inputs": {"<name>": <value> or ["<source node id>", <output index>]}}}. Not the editor\'s UI format.'
    ),
]


def _problems(items: list[Problem]) -> list[dict[str, Any]]:
    return [p.as_dict() for p in items]


def _result(report: Report) -> ValidationResult:
    return ValidationResult(
        valid=report.valid,
        runnable=report.valid and not report.partner_api_nodes,
        errors=[WorkflowProblem(**p.as_dict()) for p in report.errors],
        warnings=[WorkflowProblem(**p.as_dict()) for p in report.warnings],
        partner_api_nodes=[PartnerApiNode(**n) for n in report.partner_api_nodes],
        output_nodes=report.output_nodes,
        node_count=report.node_count,
    )


async def _validate(relay: Relay, workflow: dict[str, Any]) -> Report:
    # Fresh each time: file-picker options and installed nodes change under us.
    return validate(workflow, await relay.comfyui.object_info())


def _workflow_validate(relay: Relay) -> Callable[..., Any]:
    async def workflow_validate(workflow: WorkflowArg) -> ValidationResult:
        """Check a ComfyUI workflow (API format) against the live instance's node definitions, without running it.

        Finds unknown node classes, missing required inputs, links to nodes or outputs that do not exist, linked
        types that do not match, and constants out of range or not among a COMBO's options. Each problem names the
        node id, the input, and what was expected versus what the graph gave; types follow ComfyUI's own
        (return_type_mismatch, value_not_in_list, ...). Also lists partner-API nodes, which workflow_run refuses.
        Changes nothing. workflow_run runs this same check first.
        """
        return _result(await _validate(relay, workflow))

    return workflow_validate


# -- workflow_run -------------------------------------------------------------


class RunStarted(BaseModel):
    job_id: str = Field(description="Follow it with job_status (wait with timeout_seconds); stop it with job_cancel")
    prompt_id: str = Field(description="ComfyUI's id for the run")
    comfyui_state: str = Field(
        description="Where ComfyUI has it as this call returns: queued, running or finished; submitting if ComfyUI "
        "has not answered the submission yet"
    )
    queue_number: float | None = None
    warnings: list[WorkflowProblem] = Field(description="From the validation; they did not stop the run")


def refuse_partner_nodes(nodes: list[dict[str, Any]]) -> RelayError:
    names = ", ".join(f"{n['node_id']} ({n['class_type']})" for n in nodes)
    return RelayError(
        "partner_api_nodes_refused",
        f"refused: the workflow has partner-API nodes, which call paid external services and spend credits: "
        f"{names}. This server never runs them (#103). Nothing was submitted. Replace them with local nodes, or "
        "run the workflow somewhere a human has approved the spend.",
        nodes=nodes,
    )


def refuse_invalid(report: Report) -> RelayError:
    first = report.errors[0]
    where = f"node {first.node_id} ({first.class_type})" if first.node_id else "the workflow"
    on = f", input {first.input!r}" if first.input else ""
    return RelayError(
        "workflow_invalid",
        f"the workflow has {len(report.errors)} error(s), so nothing was submitted. First: {where}{on}: "
        f"{first.type}: {first.message}" + (f" ({first.details})" if first.details else ""),
        errors=_problems(report.errors),
        warnings=_problems(report.warnings),
    )


def comfyui_problems(node_errors: Any, note: str = "") -> list[dict[str, Any]]:
    """ComfyUI's /prompt node_errors, in the same shape as workflow_validate's problems."""
    problems = []
    for node_id, entry in (node_errors or {}).items() if isinstance(node_errors, dict) else ():
        for error in (entry.get("errors") or []) if isinstance(entry, dict) else ():
            if not isinstance(error, dict):
                continue
            extra = error.get("extra_info") if isinstance(error.get("extra_info"), dict) else {}
            config = extra.get("input_config")
            problem = {
                "type": error.get("type") or "comfyui_error",
                "message": f"{error.get('message')}{note}",
                "node_id": str(node_id),
                "class_type": entry.get("class_type"),
                "input": extra.get("input_name"),
                "details": error.get("details") or None,
                "expected": config[0] if isinstance(config, list) and config else None,
                "got": extra.get("received_type", extra.get("received_value")),
            }
            problems.append({k: v for k, v in problem.items() if v is not None})
    return problems


def _workflow_run(relay: Relay) -> Callable[..., Any]:
    async def workflow_run(workflow: WorkflowArg) -> RunStarted:
        """Run a ComfyUI workflow (API format) and return a job id straight away; the run continues in ComfyUI.

        It validates first, as workflow_validate does, and refuses an invalid graph with those errors. It refuses
        any graph with a partner-API node (a paid external service) outright. A graph ComfyUI itself rejects fails
        with ComfyUI's per-node errors. Then follow the job with job_status: it reports queued or running, and at
        the end the saved files, or ComfyUI's error naming the node that failed. List or fetch the files with
        workflow_outputs. Each call is a new run with new outputs.
        """
        report = await _validate(relay, workflow)
        if report.partner_api_nodes:
            raise refuse_partner_nodes(report.partner_api_nodes)
        if not report.valid:
            raise refuse_invalid(report)

        prompt_id = str(uuid.uuid4())
        progress: dict[str, Any] = {"prompt_id": prompt_id, "comfyui_state": "submitting"}
        submitted: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        # Retrieve the outcome even if nobody awaits it (this call timed out), so asyncio does not log it.
        submitted.add_done_callback(lambda f: f.cancelled() or f.exception())
        outputs = ", ".join(f"{n} ({workflow[n]['class_type']})" for n in report.output_nodes)
        job = relay.jobs.submit(
            RUN_KIND,
            lambda: run_prompt(relay.comfyui, workflow, progress, submitted),
            summary=f"workflow run: {report.node_count} nodes, outputs {outputs}",
        )
        job.progress = progress
        await asyncio.wait({submitted, job.task}, timeout=SUBMIT_WAIT_SECONDS, return_when=asyncio.FIRST_COMPLETED)
        if submitted.done() and not submitted.cancelled() and submitted.exception() is not None:
            exc = submitted.exception()
            if isinstance(exc, RelayError):
                detail = dict(exc.detail)
                if exc.code == "workflow_rejected":
                    detail["errors"] = comfyui_problems(detail.get("node_errors"))
                raise RelayError(exc.code, exc.message, retryable=exc.retryable, **detail, job_id=job.id)
            raise RelayError("job_failed", f"{type(exc).__name__}: {exc}", job_id=job.id)
        answer = submitted.result() if submitted.done() and not submitted.cancelled() else {}
        # ComfyUI accepts a graph when any output passes its checks, and drops the outputs that fail.
        dropped = comfyui_problems(
            answer.get("node_errors"), "; ComfyUI accepted the workflow but will not run the outputs that need this"
        )
        return RunStarted(
            job_id=job.id,
            prompt_id=progress["prompt_id"],
            comfyui_state=progress["comfyui_state"],
            queue_number=answer.get("number"),
            warnings=[WorkflowProblem(**p) for p in [*_problems(report.warnings), *dropped]],
        )

    return workflow_run


async def run_prompt(
    comfyui: ComfyUIClient,
    graph: dict[str, Any],
    progress: dict[str, Any],
    submitted: asyncio.Future[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The producer: submit `graph` as progress["prompt_id"], follow it to the end, and return its outputs."""
    try:
        try:
            answer = await comfyui.queue_prompt(graph, progress["prompt_id"])
        except BaseException as exc:
            if submitted is not None and not submitted.done():
                if isinstance(exc, asyncio.CancelledError):
                    submitted.cancel()
                else:
                    submitted.set_exception(exc)
            raise
        # A ComfyUI older than client-chosen ids mints its own; follow that one.
        progress.update(prompt_id=answer["prompt_id"], comfyui_state="queued")
        if submitted is not None and not submitted.done():
            submitted.set_result(answer)
        return await _follow(comfyui, progress)
    except asyncio.CancelledError:
        await stop_prompt(comfyui, progress["prompt_id"])
        raise


def _ids(items: list[Any]) -> list[tuple[Any, str]]:
    """(number, prompt_id) for each queue item, which ComfyUI sends as [number, prompt_id, ...]."""
    return [(i[0], i[1]) for i in items if isinstance(i, list) and len(i) > 1 and isinstance(i[1], str)]


async def _follow(comfyui: ComfyUIClient, progress: dict[str, Any]) -> dict[str, Any]:
    prompt_id = progress["prompt_id"]
    absent = 0
    unreachable_since: float | None = None
    while True:
        try:
            queue = await comfyui.queue()
            unreachable_since = None
            progress.pop("comfyui_error", None)
            running = [pid for _, pid in _ids(queue["queue_running"])]
            pending = sorted(_ids(queue["queue_pending"]), key=lambda item: (str(type(item[0])), item[0]))
            waiting = [pid for _, pid in pending]
            if prompt_id in running:
                progress.update(comfyui_state="running", queue_position=None)
            elif prompt_id in waiting:
                progress.update(comfyui_state="queued", queue_position=waiting.index(prompt_id))
            else:
                entry = await comfyui.history(prompt_id)
                if entry is not None:
                    progress.update(comfyui_state="finished", queue_position=None)
                    return finish(prompt_id, entry)
                absent += 1
                if absent >= VANISHED_POLLS:
                    raise RelayError(
                        "workflow_vanished",
                        f"ComfyUI has prompt {prompt_id} neither queued, running nor in its history: something "
                        "else removed it from the queue, or ComfyUI restarted",
                        prompt_id=prompt_id,
                    )
        except RelayError as exc:
            if not exc.retryable:
                raise
            unreachable_since = unreachable_since or time.monotonic()
            progress["comfyui_error"] = exc.message
            if time.monotonic() - unreachable_since > UNREACHABLE_GRACE_SECONDS:
                raise
        await asyncio.sleep(POLL_SECONDS)


def finish(prompt_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    """The job's result for a finished prompt, or its structured error."""
    status = entry.get("status") if isinstance(entry.get("status"), dict) else {}
    files, _ = collect_outputs(entry.get("outputs"))
    status_str = status.get("status_str")
    if status_str == "success" or (status_str is None and status.get("completed", True)):
        return {
            "prompt_id": prompt_id,
            "status": "success",
            "files": [{k: f[k] for k in ("node_id", "filename", "subfolder", "type")} for f in files],
        }
    for message in status.get("messages") or []:
        if not (isinstance(message, list) and len(message) == 2 and isinstance(message[1], dict)):
            continue
        kind, data = message
        if kind == "execution_error":
            node = f"node {data.get('node_id')} ({data.get('node_type')})"
            text = str(data.get("exception_message") or "").strip()
            raise RelayError(
                "workflow_execution_failed",
                f"{node} failed while running: {data.get('exception_type')}: {text}",
                prompt_id=prompt_id,
                node_id=data.get("node_id"),
                node_type=data.get("node_type"),
                exception_type=data.get("exception_type"),
                exception_message=text,
                traceback_tail="".join((data.get("traceback") or [])[-2:])[-2000:],
                files=[{k: f[k] for k in ("node_id", "filename", "subfolder", "type")} for f in files],
            )
        if kind == "execution_interrupted":
            raise RelayError(
                "workflow_interrupted",
                f"ComfyUI interrupted the run at node {data.get('node_id')} ({data.get('node_type')}). Not this job: "
                "something else stopped it (an interrupt from the ComfyUI UI or another client)",
                prompt_id=prompt_id,
                node_id=data.get("node_id"),
                node_type=data.get("node_type"),
            )
    raise RelayError(
        "workflow_failed",
        f"ComfyUI finished prompt {prompt_id} with status {status_str!r} and no error message",
        prompt_id=prompt_id,
    )


async def stop_prompt(comfyui: ComfyUIClient, prompt_id: str) -> None:
    """Stop our prompt on ComfyUI, within STOP_BUDGET_SECONDS, without touching anyone else's.

    First drop it from the queue: a no-op unless it is still waiting. Then, if
    /queue shows it running, interrupt it by id. Deleting before looking
    means a prompt that starts running in between is seen running, not missed.
    A failure is logged, not raised: the job is cancelled either way.
    """
    try:
        async with asyncio.timeout(STOP_BUDGET_SECONDS):
            await comfyui.delete_queued(prompt_id)
            queue = await comfyui.queue(cancelling=True)
            running = [pid for _, pid in _ids(queue.get("queue_running") or [])]
            if prompt_id in running:
                await comfyui.interrupt(prompt_id)
                log.info("cancelled: interrupted running prompt %s", prompt_id)
            else:
                log.info("cancelled: removed prompt %s from the queue, if it was there", prompt_id)
    except (TimeoutError, RelayError) as exc:
        log.warning("could not stop prompt %s on ComfyUI while cancelling its job: %s", prompt_id, exc)


# -- workflow_outputs ---------------------------------------------------------


class OutputFile(BaseModel):
    node_id: str
    kind: str = Field(description="What the node called the list: images, gifs, audio, video, ...")
    filename: str
    subfolder: str
    type: str = Field(description="ComfyUI's folder: output, or temp for previews")
    size_bytes: int | None = Field(description="From ComfyUI; null when not asked (past the first files) or unknown")
    mime_type: str | None
    view_path: str = Field(
        description="The file on ComfyUI's own HTTP API, for a person or tool that can reach ComfyUI directly. "
        "Through this server, fetch it with workflow_outputs(fetch=<filename>)"
    )


class OutputsView(BaseModel):
    job_id: str
    prompt_id: str
    job_state: str
    comfyui_status: str | None = Field(description="ComfyUI's status_str: success, error, ...")
    files: list[OutputFile]
    other_outputs: dict[str, Any] = Field(description="Non-file outputs by node id, such as text; long values cut")
    fetched: str | None = Field(description="The file returned inline after this JSON, if one was asked for")
    inline_limit_bytes: int


def collect_outputs(outputs: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(files, other outputs) from a history entry's `outputs`."""
    files, other = [], {}
    for node_id, produced in (outputs or {}).items() if isinstance(outputs, dict) else ():
        if not isinstance(produced, dict):
            continue
        for kind, items in produced.items():
            if isinstance(items, list) and items and all(isinstance(i, dict) and "filename" in i for i in items):
                for item in items:
                    files.append(
                        {
                            "node_id": str(node_id),
                            "kind": kind,
                            "filename": str(item["filename"]),
                            "subfolder": str(item.get("subfolder") or ""),
                            "type": str(item.get("type") or "output"),
                        }
                    )
            else:
                text = json.dumps(items, default=str)
                other.setdefault(str(node_id), {})[kind] = items if len(text) <= 2000 else text[:2000] + "..."
    return files, other


def _ref(f: dict[str, Any]) -> dict[str, str]:
    return {"filename": f["filename"], "subfolder": f["subfolder"], "type": f["type"]}


def _workflow_outputs(relay: Relay) -> Callable[..., Any]:
    async def workflow_outputs(
        job_id: str,
        fetch: str | None = Field(
            default=None,
            description="A filename from this job's files (or subfolder/filename) to return inline: an image or "
            f"audio as content the model can see or hear, anything else as a resource. At most {MAX_INLINE_BYTES} "
            "bytes; leave it out to list only.",
        ),
    ) -> Annotated[CallToolResult, OutputsView]:
        """List the files a finished workflow_run job saved, with their sizes, and optionally return one inline.

        Takes the job_id from workflow_run. Lists each file (node, filename, subfolder, type, size) and any
        non-file outputs such as text; works for failed or cancelled runs too, which may have saved some files.
        Nothing is streamed unless asked: pass fetch=<filename> to get that one file's bytes, up to a size cap.
        Changes nothing.
        """
        job = relay.jobs.get(job_id)
        prompt_id = (job.progress or {}).get("prompt_id")
        if job.kind != RUN_KIND or not prompt_id:
            raise RelayError(
                "not_a_workflow_job", f"job {job_id} is a {job.kind} job, not a workflow run", kind=job.kind
            )
        if not job.state.finished:
            raise RelayError(
                "job_not_finished",
                f"job {job_id} is still {job.status.value}; wait for it with job_status(timeout_seconds=...)",
                retryable=True,
                state=job.status.value,
            )
        entry = await relay.comfyui.history(prompt_id)
        if entry is None:
            raise RelayError(
                "outputs_unavailable",
                f"ComfyUI has no history for prompt {prompt_id}: the run never started there, or ComfyUI's history "
                "was cleared or it restarted since",
                prompt_id=prompt_id,
            )
        files, other = collect_outputs(entry.get("outputs"))
        sizes = await asyncio.gather(
            *(relay.comfyui.view_size(_ref(f)) for f in files[:MAX_SIZED_FILES]), return_exceptions=True
        )
        listed = [
            OutputFile(
                **f,
                size_bytes=sizes[i] if i < len(sizes) and isinstance(sizes[i], int) else None,
                mime_type=mimetypes.guess_type(f["filename"])[0],
                view_path="/view?" + urlencode(_ref(f)),
            )
            for i, f in enumerate(files)
        ]
        status = entry.get("status") if isinstance(entry.get("status"), dict) else {}
        view = OutputsView(
            job_id=job_id,
            prompt_id=prompt_id,
            job_state=job.status.value,
            comfyui_status=status.get("status_str"),
            files=listed,
            other_outputs=other,
            fetched=None,
            inline_limit_bytes=MAX_INLINE_BYTES,
        )
        content: list[Any] = []
        if fetch is not None:
            wanted = next((f for f in listed if fetch in (f.filename, f"{f.subfolder}/{f.filename}")), None)
            if wanted is None:
                raise RelayError(
                    "unknown_output",
                    f"job {job_id} saved no file {fetch!r}",
                    expected=[f.filename for f in listed],
                )
            if wanted.size_bytes is not None and wanted.size_bytes > MAX_INLINE_BYTES:
                raise RelayError(
                    "output_too_large",
                    f"{wanted.filename} is {wanted.size_bytes} bytes, over the {MAX_INLINE_BYTES} returned inline. "
                    f"It stays on ComfyUI at {wanted.view_path}",
                    limit=MAX_INLINE_BYTES,
                    size_bytes=wanted.size_bytes,
                )
            data, served_type = await relay.comfyui.view_bytes(
                {"filename": wanted.filename, "subfolder": wanted.subfolder, "type": wanted.type}, MAX_INLINE_BYTES
            )
            content.append(_inline(wanted, data, served_type))
            view.fetched = wanted.filename
        structured = view.model_dump(mode="json")
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(structured)), *content],
            structured_content=structured,
        )

    return workflow_outputs


def _inline(f: OutputFile, data: bytes, served_type: str) -> Any:
    from mcp_types import BlobResourceContents, EmbeddedResource

    mime = (served_type or "").split(";")[0].strip() or f.mime_type or "application/octet-stream"
    encoded = base64.b64encode(data).decode()
    if mime.startswith("image/"):
        return ImageContent(type="image", data=encoded, mime_type=mime)
    if mime.startswith("audio/"):
        return AudioContent(type="audio", data=encoded, mime_type=mime)
    return EmbeddedResource(
        type="resource",
        resource=BlobResourceContents(uri=f"comfyui:{f.view_path}", mime_type=mime, blob=encoded),
    )


# -- workflow_upload_input ----------------------------------------------------


class Uploaded(BaseModel):
    name: str = Field(description="The name ComfyUI stored it under: use this in LoadImage's image input")
    subfolder: str
    type: str = Field(description="Always input")
    size_bytes: int
    requested_name: str = Field(description="The name asked for, after sanitising")
    renamed: bool = Field(
        description="ComfyUI already had a different file by that name, so it stored this one as name (n).ext"
    )


def sanitise_filename(name: str) -> str:
    """A plain file name, safe to hand ComfyUI: no directories, no leading dots, a short safe alphabet."""
    base = unicodedata.normalize("NFKC", name).replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._()+ -]", "_", base).strip(" .")
    if not cleaned.strip("_."):
        raise RelayError(
            "invalid_filename",
            f"{name!r} has no usable file name once directories and unsafe characters are removed; name the file "
            "like picture.png",
            got=name,
        )
    if len(cleaned) > MAX_FILENAME_CHARS:
        stem, dot, ext = cleaned.rpartition(".")
        ext = f"{dot}{ext}" if dot and len(ext) <= 10 else ""
        cleaned = (stem if ext else cleaned)[: MAX_FILENAME_CHARS - len(ext)] + ext
    return cleaned


def _workflow_upload_input(relay: Relay) -> Callable[..., Any]:
    async def workflow_upload_input(
        filename: str = Field(description="The file name to store it as, such as photo.png. Directories are dropped"),
        content_base64: str = Field(
            max_length=(MAX_UPLOAD_BYTES + 2) // 3 * 4 + 100,
            description=f"The file's bytes, base64-encoded (a data: URL prefix is accepted). At most "
            f"{MAX_UPLOAD_BYTES} bytes decoded.",
        ),
    ) -> Uploaded:
        """Upload a file (an image, a mask, audio, video) into ComfyUI's input directory, for LoadImage and friends.

        Returns the name ComfyUI stored it under: put that in the loading node's input. It never overwrites: a
        different file with the same name is stored as name (1).ext, and the same bytes again reuse the file
        already there. Writes only to ComfyUI's input directory, through ComfyUI's own upload API.
        """
        clean = sanitise_filename(filename)
        payload = content_base64.strip()
        if payload.startswith("data:") and "," in payload:
            payload = payload.split(",", 1)[1]
        try:
            data = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RelayError("invalid_base64", f"content_base64 is not valid base64: {exc}") from None
        if not data:
            raise RelayError("empty_upload", "the file is empty")
        if len(data) > MAX_UPLOAD_BYTES:
            raise RelayError(
                "upload_too_large",
                f"the file is {len(data)} bytes; the most this server uploads is {MAX_UPLOAD_BYTES}",
                limit=MAX_UPLOAD_BYTES,
                size_bytes=len(data),
            )
        content_type = mimetypes.guess_type(clean)[0] or "application/octet-stream"
        stored = await relay.comfyui.upload_input(clean, data, content_type)
        return Uploaded(
            name=stored["name"],
            subfolder=str(stored.get("subfolder") or ""),
            type=str(stored.get("type") or "input"),
            size_bytes=len(data),
            requested_name=clean,
            renamed=stored["name"] != clean,
        )

    return workflow_upload_input


# -- registration --------------------------------------------------------------


def workflow_tool_specs(spec: Callable[..., Any]) -> tuple[Any, ...]:
    """The ToolSpecs for tools.py's registry. `spec` is ToolSpec, passed in to keep the import one-way.

    Annotations (MCP hints; clients may show them, gate on them, or ignore them):
    - workflow_validate, workflow_outputs: read-only.
    - workflow_run: not read-only (it queues work and ComfyUI writes new output files), but not destructive
      either: it replaces and deletes nothing (SaveImage numbers files, never overwrites). Not idempotent: each
      call is another run with new outputs.
    - workflow_upload_input: not read-only (it adds a file to ComfyUI's input directory), not destructive (it
      never overwrites: ComfyUI renames a clash), idempotent (the same bytes under the same name are stored once).
    All are closed-world: they reach only the configured ComfyUI, and a graph with partner-API nodes, which
    would reach further, is refused.
    """
    run = frozenset({"run"})
    return (
        spec(
            "workflow_validate",
            run,
            _workflow_validate,
            ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False),
        ),
        spec(
            "workflow_run",
            run,
            _workflow_run,
            ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False),
        ),
        spec(
            "workflow_outputs",
            run,
            _workflow_outputs,
            ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False),
        ),
        spec(
            "workflow_upload_input",
            run,
            _workflow_upload_input,
            ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False),
        ),
    )
