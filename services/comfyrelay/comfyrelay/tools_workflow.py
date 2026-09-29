"""The workflow tools (#132), all in the `run` profile.

    workflow_validate      check a graph's structure, classes and partner-API nodes against /object_info
    workflow_run           submit it; returns a job id at once (follow it with job_status)
    workflow_outputs       a finished run's files, and one file's bytes on request
    workflow_upload_input  put a file into ComfyUI's input directory

A run is a job (jobs.py). Its producer submits the graph to ComfyUI's /prompt
with a prompt id of its own making, follows it through /api/jobs/<id> (and
/history/<id> once it ends), and maps how it ended into the job's result or
structured error. Cancelled by job_cancel, it stops the prompt with ComfyUI's
atomic cancel, /api/jobs/<id>/cancel, and checks that it stopped, before it
re-raises: the producer contract in jobs.py, inside its 3s budget. What it
could not confirm, it says in progress.stop. Cancelled because the relay is
stopping, it leaves the prompt running on ComfyUI (owner decision on #145).

A run's job id is its prompt id, so a restarted relay re-attaches to it: an id
this server does not hold is looked up on ComfyUI, the source of truth (#146,
"re-attach" below).

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
import weakref
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Annotated, Any, Literal
from urllib.parse import urlencode

from mcp_types import AudioContent, CallToolResult, ImageContent, TextContent, ToolAnnotations
from pydantic import BaseModel, Field

from .comfyui import ComfyUIClient, ComfyUIError
from .errors import RelayError
from .jobs import MAX_WAIT_SECONDS, AlreadyFinished, current_job
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
# Of that, what is kept for the cancel itself when a submission is still in
# flight: the rest is spent waiting for ComfyUI to answer it.
CANCEL_RESERVE_SECONDS = 1.0
# How often the unwind asks ComfyUI whether the prompt has stopped.
STOP_CHECK_SECONDS = 0.2
# A stop still unsettled when the budget runs out carries on in the background,
# so job_status catches up with how the prompt ended: up to 60 checks, 0.5s apart.
SETTLE_CHECKS = 60
SETTLE_SECONDS = 0.5
# How long one /object_info (1.8 MB at v0.37.0, more with custom nodes) and one
# /queue (it carries every queued graph) are shared between callers.
OBJECT_INFO_TTL_SECONDS = 10.0
QUEUE_TTL_SECONDS = 2.0
# How long workflow_run waits for ComfyUI to accept the graph before it
# returns the job id anyway.
SUBMIT_WAIT_SECONDS = 30.0
# Uploads arrive base64-encoded inside one MCP message.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_BASE64_CHARS = (MAX_UPLOAD_BYTES + 2) // 3 * 4
# The HTTP transport's limit on one request body (server.py). The SDK's default,
# 4 MiB, would refuse a 3 MiB upload before the tool ran, with an opaque 413.
# This fits the largest upload's base64 plus the JSON-RPC envelope, with 1 MiB
# to spare, so an upload a little over the cap reaches the tool and gets
# `upload_too_large`; only one over about 10.75 MiB meets the transport's 413.
# The body is read only after the token check (server.TokenAuth).
MAX_REQUEST_BODY_BYTES = MAX_UPLOAD_BASE64_CHARS + 1024 * 1024
# How many uploads decode and send at once: each holds its decoded bytes and a
# multipart copy while it does (README: the memory a run-profile sidecar needs).
UPLOAD_CONCURRENCY = 1
# The most workflow_outputs returns inline, and how many files it sizes.
MAX_INLINE_BYTES = 5_000_000
MAX_SIZED_FILES = 32
MAX_FILENAME_CHARS = 120


# -- workflow_validate --------------------------------------------------------


class WorkflowProblem(BaseModel):
    type: str = Field(
        description="An error type: ComfyUI's own (return_type_mismatch, value_not_in_list, ...) when ComfyUI "
        "rejected the graph, or this server's structural ones (missing_node_type, linked_node_missing, ...)"
    )
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
    valid: bool = Field(
        description="No structural errors. Input types and values are not checked here: ComfyUI checks them when "
        "workflow_run submits the graph"
    )
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


class _Read:
    """One read of ComfyUI, shared: its future, and when it completed (None while in flight)."""

    def __init__(self, future: asyncio.Future[Any]) -> None:
        self.future = future
        self.done_at: float | None = None
        future.add_done_callback(self._done)

    def _done(self, future: asyncio.Future[Any]) -> None:
        self.done_at = time.monotonic()
        if not future.cancelled():
            future.exception()  # retrieved, so asyncio does not log it

    def fresh(self, ttl: float) -> bool:
        if not self.future.done():
            return True  # in flight: wait for it rather than send another
        if self.future.cancelled() or self.future.exception() is not None:
            return False  # a failed read is not kept
        return time.monotonic() - (self.done_at or 0.0) <= ttl


_object_info: weakref.WeakKeyDictionary[ComfyUIClient, _Read] = weakref.WeakKeyDictionary()
_queue: weakref.WeakKeyDictionary[ComfyUIClient, _Read] = weakref.WeakKeyDictionary()


async def _shared(
    cache: weakref.WeakKeyDictionary[ComfyUIClient, _Read],
    comfyui: ComfyUIClient,
    ttl: float,
    fetch: Callable[[], Awaitable[Any]],
) -> Any:
    """One read shared by every caller until `ttl` seconds after it completed, and one request in flight at a
    time. A failed or cancelled read is not kept."""
    held = cache.get(comfyui)
    if held is None or not held.fresh(ttl):
        held = cache[comfyui] = _Read(asyncio.ensure_future(fetch()))
    return await asyncio.shield(held.future)


async def _validate(relay: Relay, workflow: dict[str, Any]) -> Report:
    # Shared for a few seconds: file-picker options and installed nodes change, but rarely within a run's setup;
    # an upload drops the copy (workflow_upload_input).
    info = await _shared(_object_info, relay.comfyui, OBJECT_INFO_TTL_SECONDS, relay.comfyui.object_info)
    return validate(workflow, info)


def _workflow_validate(relay: Relay) -> Callable[..., Any]:
    async def workflow_validate(workflow: WorkflowArg) -> ValidationResult:
        """Check a ComfyUI workflow (API format) for what can be known without submitting it; runs nothing.

        Finds a graph that is not in API format, node classes this instance does not have (with near names),
        links to nodes or outputs that do not exist, and a graph with no output node, each naming the node id and
        input. Lists partner-API nodes, which workflow_run refuses. It does not check input types or values
        (required inputs, COMBO choices, number ranges): ComfyUI has no dry run, so those are checked by ComfyUI
        itself when workflow_run submits the graph, and come back as its errors. Changes nothing. workflow_run
        runs this same check first.
        """
        return _result(await _validate(relay, workflow))

    return workflow_validate


# -- workflow_run -------------------------------------------------------------


class RunStarted(BaseModel):
    job_id: str = Field(
        description="Follow it with job_status (wait with timeout_seconds); stop it with job_cancel. The same as "
        "prompt_id, so job_status and workflow_outputs still find the run after this server restarts"
    )
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

        It runs workflow_validate's check first, and refuses a graph that fails it. It refuses any graph with a
        partner-API node (a paid external service) outright. ComfyUI then checks input types and values as it
        accepts the graph: one it rejects fails at once with workflow_rejected, carrying ComfyUI's per-node errors
        (type, node id, input, details). Then follow the job with job_status: it reports queued or running, and at
        the end the saved files, or ComfyUI's error naming the node that failed. List or fetch the files with
        workflow_outputs. Each call is a new run with new outputs. job_cancel stops it on ComfyUI.

        What the graph does is up to its nodes: this server reaches only ComfyUI, but a custom node installed there
        may write anywhere ComfyUI can, or reach the network. Only partner-API nodes are refused.
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
            job_id=prompt_id,  # a restarted relay finds the run on ComfyUI by this id (#146)
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


# Tasks nothing else holds: a submission left in flight, a cancel sent late.
_background: set[asyncio.Future[Any]] = set()


def _keep(task: asyncio.Future[Any]) -> asyncio.Future[Any]:
    _background.add(task)
    task.add_done_callback(_background.discard)
    return task


def _resolve(submitted: asyncio.Future[Any] | None, *, result: Any = None, exc: BaseException | None = None) -> None:
    if submitted is None or submitted.done():
        return
    if isinstance(exc, asyncio.CancelledError):
        submitted.cancel()
    elif exc is not None:
        submitted.set_exception(exc)
    else:
        submitted.set_result(result)


async def run_prompt(
    comfyui: ComfyUIClient,
    graph: dict[str, Any],
    progress: dict[str, Any],
    submitted: asyncio.Future[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The producer: submit `graph` as progress["prompt_id"], follow it to the end, and return its outputs.

    The submission runs as its own task and is awaited through a shield: a
    cancel must not cut the POST short, because ComfyUI goes on queueing a
    prompt whose client hung up, and a stop sent first would miss it.
    """
    post = _keep(asyncio.ensure_future(comfyui.queue_prompt(graph, progress["prompt_id"])))
    post.add_done_callback(lambda f: f.cancelled() or f.exception())
    try:
        answer = await asyncio.shield(post)
        # A ComfyUI older than client-chosen ids mints its own; follow that one.
        progress.update(prompt_id=answer["prompt_id"], comfyui_state="queued")
        _resolve(submitted, result=answer)
        return await _follow(comfyui, progress)
    except asyncio.CancelledError as exc:
        _resolve(submitted, exc=exc)
        finished = await _unwind(comfyui, progress, post)
        if finished is not None:
            raise finished from None
        raise
    except BaseException as exc:
        _resolve(submitted, exc=exc)
        raise


def _ids(items: list[Any]) -> list[tuple[Any, str]]:
    """(number, prompt_id) for each queue item, which ComfyUI sends as [number, prompt_id, ...]."""
    return [(i[0], i[1]) for i in items if isinstance(i, list) and len(i) > 1 and isinstance(i[1], str)]


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("inf")


async def _queue_position(comfyui: ComfyUIClient, prompt_id: str) -> int | None:
    """How many prompts wait ahead of this one (0: it is next), from one /queue read shared by every run."""
    queue = await _shared(_queue, comfyui, QUEUE_TTL_SECONDS, comfyui.queue)
    waiting = [pid for _, pid in sorted(_ids(queue.get("queue_pending") or []), key=lambda i: _number(i[0]))]
    return waiting.index(prompt_id) if prompt_id in waiting else None


async def _where(comfyui: ComfyUIClient, prompt_id: str, jobs_api: bool) -> tuple[str, dict[str, Any] | None]:
    """("queued" | "running" | "finished" | "absent", its /history entry once finished)."""
    if jobs_api:
        job = await comfyui.job(prompt_id)  # about 150 bytes while it is pending or running
        status = None if job is None else job["status"]
        if status in ("pending", "in_progress"):
            return ("queued" if status == "pending" else "running"), None
    else:  # a ComfyUI without the jobs API: /queue, which carries every queued graph
        queue = await comfyui.queue()
        if prompt_id in [pid for _, pid in _ids(queue["queue_running"])]:
            return "running", None
        if prompt_id in [pid for _, pid in _ids(queue["queue_pending"])]:
            return "queued", None
    entry = await comfyui.history(prompt_id)
    return ("finished", entry) if entry is not None else ("absent", None)


async def _follow(comfyui: ComfyUIClient, progress: dict[str, Any]) -> dict[str, Any]:
    prompt_id = progress["prompt_id"]
    absent = 0
    jobs_api = True
    unreachable_since: float | None = None
    while True:
        try:
            where, entry = await _where(comfyui, prompt_id, jobs_api)
            unreachable_since = None
            progress.pop("comfyui_error", None)
            if where == "finished":
                progress.update(comfyui_state="finished", queue_position=None)
                return finish(prompt_id, entry)
            absent = absent + 1 if where == "absent" else 0  # consecutive polls only
            if where == "absent":
                if absent >= VANISHED_POLLS:
                    raise RelayError(
                        "workflow_vanished",
                        f"ComfyUI has prompt {prompt_id} neither queued, running nor in its history: something "
                        "else removed it from the queue, or ComfyUI restarted",
                        prompt_id=prompt_id,
                    )
            elif where == "running":
                progress.update(comfyui_state="running", queue_position=None)
            else:
                progress.update(comfyui_state="queued", queue_position=await _queue_position(comfyui, prompt_id))
        except ComfyUIError as exc:
            if exc.code == "jobs_api_unavailable":
                jobs_api = False
                continue
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


async def _unwind(
    comfyui: ComfyUIClient, progress: dict[str, Any], post: asyncio.Future[Any]
) -> AlreadyFinished | None:
    """After a cancel: stop the prompt on ComfyUI (job_cancel), or leave it running (the relay is stopping).

    The stop runs as its own task, so a second cancel cannot abort it half
    way (jobs.py delivers one; this holds even if something else sends
    another). It is waited on for STOP_BUDGET_SECONDS at most. Returns
    AlreadyFinished when the prompt had finished before the cancel took
    effect, for the producer to raise.
    """
    job = current_job()
    if job is not None and job.cancel_reason == "shutdown":
        progress["stop"] = "left_running"
        log.info("relay stopping: prompt %s is left running on ComfyUI", progress["prompt_id"])
        return None
    loop = asyncio.get_running_loop()
    deadline = loop.time() + STOP_BUDGET_SECONDS
    stopping = _keep(asyncio.ensure_future(stop_prompt(comfyui, progress, post, deadline)))
    while not stopping.done() and (remaining := deadline - loop.time()) > 0:
        try:
            await asyncio.wait({stopping}, timeout=remaining)
        except asyncio.CancelledError:
            continue  # cancelled again: the stop goes on, inside the same deadline
    if not stopping.done():
        _stop(progress, "unconfirmed", f"ComfyUI did not confirm the stop within {STOP_BUDGET_SECONDS}s")
        return None
    return stopping.result()


def _stop(progress: dict[str, Any], outcome: str, detail: str | None = None) -> None:
    """Record how the stop went; a later, better answer replaces an earlier one's detail too."""
    progress["stop"] = outcome
    if detail is None:
        progress.pop("stop_detail", None)
    else:
        progress["stop_detail"] = detail


async def stop_prompt(
    comfyui: ComfyUIClient, progress: dict[str, Any], post: asyncio.Future[Any], deadline: float
) -> AlreadyFinished | None:
    """Stop our prompt on ComfyUI, and record in progress["stop"] what is known about it:

        confirmed         ComfyUI shows it cancelled: dequeued before it ran, or interrupted
        already_finished  it had finished before the cancel took effect; its outputs, if any, are in
                          ComfyUI, and the job ends as the prompt did (succeeded with its result, or failed)
        unconfirmed       it could not be checked in time (stop_detail says why); the stop carries on in
                          the background, and replaces this with how the prompt ended once ComfyUI says
        not_stopped       it is running, and this ComfyUI has no atomic cancel
        not_needed        ComfyUI refused the submission, so nothing was queued

    ComfyUI's own terminal status decides between the first two: "cancelled"
    is our stop, "completed" or "failed" means the prompt got there first.

    A submission still in flight is waited for first, leaving
    CANCEL_RESERVE_SECONDS for the cancel. One that does not answer in time
    is cancelled by id anyway, and again when it answers. Retryable errors
    (a timeout, a reset connection) are retried until the deadline.
    """
    loop = asyncio.get_running_loop()
    if not post.done():
        await asyncio.wait({post}, timeout=max(0.0, deadline - loop.time() - CANCEL_RESERVE_SECONDS))
    if post.done() and not post.cancelled() and getattr(post.exception(), "code", None) == "workflow_rejected":
        _stop(progress, "not_needed")
        return None
    last = "no answer from ComfyUI"
    while True:
        prompt_id = _answered_id(post) or progress["prompt_id"]
        progress["prompt_id"] = prompt_id
        try:
            cancelled = await comfyui.cancel_job(prompt_id)
            if not post.done():
                post.add_done_callback(lambda f: _cancel_when_answered(comfyui, progress, f))
                _stop(
                    progress,
                    "unconfirmed",
                    "ComfyUI had not answered the submission; it was cancelled by id, and is cancelled again if "
                    "ComfyUI answers",
                )
                return None
            if _answered_id(post) not in (None, prompt_id):
                continue  # the submission answered during that cancel, with an id of ComfyUI's own: cancel that
            if cancelled is None:
                return await _stop_without_jobs_api(comfyui, progress, prompt_id)
            job = await comfyui.job(prompt_id, cancelling=True)
            status = None if job is None else job["status"]
            if status in (None, "cancelled"):
                _stop(progress, "confirmed")
                return None
            if status in ("completed", "failed"):
                return await _already_finished(comfyui, progress, prompt_id)
            last = f"ComfyUI still reports it {status}"
            # ComfyUI clears its interrupt flag as a prompt starts executing (execution.py, execute_async), so an
            # interrupt that lands just as the prompt leaves the queue is lost. The cancel is atomic and targeted,
            # so the loop sends it again.
        except ComfyUIError as exc:
            if not exc.retryable:
                _stop(progress, "unconfirmed", exc.message)
                log.warning("could not confirm prompt %s stopped on ComfyUI: %s", prompt_id, exc.message)
                return None
            last = exc.message
        if loop.time() + STOP_CHECK_SECONDS > deadline:
            _stop(progress, "unconfirmed", last)
            _keep(asyncio.ensure_future(_settle(comfyui, progress, prompt_id, "the stop's budget ran out")))
            return None
        await asyncio.sleep(STOP_CHECK_SECONDS)


def _answered_id(post: asyncio.Future[Any]) -> str | None:
    if post.done() and not post.cancelled() and post.exception() is None:
        return post.result()["prompt_id"]
    return None


async def _stop_without_jobs_api(
    comfyui: ComfyUIClient, progress: dict[str, Any], prompt_id: str
) -> AlreadyFinished | None:
    """No atomic cancel on this ComfyUI: dequeue it, and never send /interrupt, which could stop someone else's
    prompt."""
    await comfyui.delete_queued(prompt_id)
    queue = await comfyui.queue(cancelling=True)
    if prompt_id in [pid for _, pid in _ids(queue["queue_running"])]:
        _stop(
            progress,
            "not_stopped",
            "it is running, and this ComfyUI has no atomic cancel (/api/jobs/<id>/cancel); an /interrupt could stop "
            "another client's prompt, so it is left to finish",
        )
        return None
    if await comfyui.history(prompt_id) is not None:
        return await _already_finished(comfyui, progress, prompt_id)
    _stop(progress, "confirmed")
    return None


async def _already_finished(comfyui: ComfyUIClient, progress: dict[str, Any], prompt_id: str) -> AlreadyFinished:
    """The prompt got to the end before the cancel: the job ends as it did, and its outputs stay reachable."""
    entry = await comfyui.history(prompt_id)
    progress.update(comfyui_state="finished", queue_position=None)
    _stop(progress, "already_finished")
    if entry is None:
        return AlreadyFinished(error=RelayError("workflow_vanished", f"ComfyUI has no history for {prompt_id}"))
    try:
        return AlreadyFinished(result=finish(prompt_id, entry))
    except RelayError as exc:
        return AlreadyFinished(error=exc)


def _cancel_when_answered(comfyui: ComfyUIClient, progress: dict[str, Any], post: asyncio.Future[Any]) -> None:
    if not post.cancelled() and post.exception() is None:
        progress["prompt_id"] = post.result()["prompt_id"]
        why = "its submission was answered after its job was cancelled"
        _keep(asyncio.ensure_future(_settle(comfyui, progress, progress["prompt_id"], why)))


async def _settle(comfyui: ComfyUIClient, progress: dict[str, Any], prompt_id: str, why: str) -> None:
    """Carry a stop on in the background: cancel again while ComfyUI still has the prompt queued or running, and
    record how it ended (confirmed, or already_finished), so job_status catches up. Logs what happened."""
    outcome = f"still queued or running after {SETTLE_CHECKS} checks"
    for _ in range(SETTLE_CHECKS):
        try:
            if await comfyui.cancel_job(prompt_id) is None:
                await comfyui.delete_queued(prompt_id)
                outcome = "dequeued; this ComfyUI has no atomic cancel, so a running prompt could not be stopped"
                break
            job = await comfyui.job(prompt_id, cancelling=True)
            status = None if job is None else job["status"]
            if status in (None, "cancelled"):
                _stop(progress, "confirmed")
                outcome = "stopped"
                break
            if status in ("completed", "failed"):
                await _already_finished(comfyui, progress, prompt_id)
                outcome = f"it had already {status}"
                break
        except ComfyUIError as exc:
            if not exc.retryable:
                outcome = f"not confirmed: {exc.message}"
                break
        await asyncio.sleep(SETTLE_SECONDS)
    unsettled = outcome.startswith(("still", "not", "dequeued"))
    log.log(
        logging.WARNING if unsettled else logging.INFO,
        "stop of prompt %s, carried on because %s: %s",
        prompt_id,
        why,
        outcome,
    )


# -- re-attach (#146) ---------------------------------------------------------
#
# A run's job id is its prompt id. So when job_status, workflow_outputs or job_cancel get an id this server does not
# hold (it restarted, or dropped the finished job), the run is looked up on ComfyUI, the source of truth, with
# GET /api/jobs/<id>: a small {id, status, create_time} while the prompt waits or runs, and once it has ended its
# execution_status (the /history status) and outputs too. That is mapped into the shapes a run held here has,
# through the same finish(), and marked source "comfyui". Nothing about the run is kept here.

# ComfyUI's job statuses (v0.37.0, comfy_execution/jobs.py JobStatus) as the state a run held here reports. A live
# run is "running" whether ComfyUI has it queued or running; progress.comfyui_state tells those apart.
REATTACHED_STATES = {
    "pending": "running",
    "in_progress": "running",
    "completed": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
}
FINISHED_STATUSES = frozenset({"completed", "failed", "cancelled"})
REATTACHED_SUMMARY = "workflow run, found on ComfyUI: this server does not hold it (it restarted, or dropped the job)"


async def comfyui_job(comfyui: ComfyUIClient, prompt_id: str) -> dict[str, Any]:
    """ComfyUI's record of a prompt this server does not hold, or `unknown_job` when ComfyUI has none either."""
    try:
        job = await comfyui.job(prompt_id)
        why = (
            "and ComfyUI has no prompt by that id: a prompt cancelled before it ran leaves no record there, and "
            "ComfyUI forgets its history when it restarts"
        )
    except ComfyUIError as exc:
        if exc.code != "jobs_api_unavailable":
            raise
        job, why = None, "and this ComfyUI has no /api/jobs to look it up in"
    if job is None:
        raise RelayError(
            "unknown_job",
            f"no job {prompt_id!r}: this server does not hold it (it never existed here, was dropped after "
            f"finishing, or the server restarted), {why}",
            job_id=prompt_id,
        )
    return job


def _seconds(ms: Any) -> float | None:
    return ms / 1000 if isinstance(ms, (int, float)) else None


async def reattached(comfyui: ComfyUIClient, prompt_id: str, job: dict[str, Any]) -> dict[str, Any]:
    """A job view (tools.JobView's fields) of a run found on ComfyUI; `job` is its GET /api/jobs/<id>."""
    status = job["status"]
    finished = status in FINISHED_STATUSES
    progress: dict[str, Any] = {
        "prompt_id": prompt_id,
        "comfyui_state": "finished" if finished else "queued" if status == "pending" else "running",
    }
    if status == "pending":
        progress["queue_position"] = await _queue_position(comfyui, prompt_id)
    state, result, error = REATTACHED_STATES.get(status, "running"), None, None
    if status in ("completed", "failed"):
        try:
            result = finish(prompt_id, {"status": job.get("execution_status"), "outputs": job.get("outputs")})
        except RelayError as exc:
            state, error = "failed", exc.as_dict()
    return {
        "job_id": prompt_id,
        "kind": RUN_KIND,
        "summary": REATTACHED_SUMMARY,
        "state": state,
        "finished": finished,
        "created_at": _seconds(job.get("create_time")),
        "started_at": _seconds(job.get("execution_start_time")),
        "finished_at": _seconds(job.get("execution_end_time")),
        "result": result,
        "error": error,
        "progress": progress,
        "source": "comfyui",
    }


async def reattach_status(comfyui: ComfyUIClient, prompt_id: str, timeout: float) -> dict[str, Any]:
    """job_status for an id this server does not hold: ComfyUI's view of the run, after waiting up to `timeout`
    seconds for it to finish."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + min(max(timeout, 0.0), MAX_WAIT_SECONDS)
    job = await comfyui_job(comfyui, prompt_id)
    while job["status"] not in FINISHED_STATUSES and loop.time() + POLL_SECONDS <= deadline:
        await asyncio.sleep(POLL_SECONDS)
        job = await comfyui_job(comfyui, prompt_id)
    return await reattached(comfyui, prompt_id, job)


async def reattach_cancel(relay: Relay, prompt_id: str) -> dict[str, Any]:
    """job_cancel for an id this server does not hold. A finished run has nothing to cancel and is reported as it
    ended. An unfinished one is refused: this server cannot tell whether it submitted the prompt, and cancelling by
    id alone would let an agent stop another client's prompt."""
    job = await comfyui_job(relay.comfyui, prompt_id)
    if job["status"] in FINISHED_STATUSES:
        return await reattached(relay.comfyui, prompt_id, job)
    raise RelayError(
        "job_not_owned",
        f"refused: this server does not hold job {prompt_id}, so it cannot tell whether it submitted that prompt, "
        "and cancelling it could stop another client's work. job_status and workflow_outputs still follow it",
        job_id=prompt_id,
        comfyui_status=job["status"],
    )


# -- workflow_outputs ---------------------------------------------------------


class OutputFile(BaseModel):
    node_id: str
    kind: str = Field(description="What the node called the list: images, gifs, audio, video, ...")
    filename: str
    subfolder: str
    type: str = Field(description="ComfyUI's folder: output, or temp for previews")
    size_bytes: int | None = Field(
        description="From ComfyUI; null when not asked (past the first 32 files, or not the one fetched) or unknown"
    )
    mime_type: str | None
    view_path: str = Field(
        description="The file on ComfyUI's own HTTP API, for a person or tool that can reach ComfyUI directly. "
        "Through this server, fetch it with workflow_outputs(fetch=<filename>)"
    )


class OutputsView(BaseModel):
    job_id: str
    prompt_id: str
    job_state: str
    source: Literal["relay", "comfyui"] = Field(
        description="relay: a run this server holds. comfyui: one it does not hold (it restarted), looked up on "
        "ComfyUI by its id"
    )
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
        non-file outputs such as text; works for failed or cancelled runs too, which may have saved some files,
        and after this server restarts (the run is then looked up on ComfyUI by its id, and marked source
        "comfyui"). Nothing is streamed unless asked: pass fetch=<filename> to get that one file's bytes, up to a
        size cap. Changes nothing.
        """
        job = relay.jobs.find(job_id)
        if job is None:  # not held here: look the run up on ComfyUI (#146)
            found = await comfyui_job(relay.comfyui, job_id)
            prompt_id, source = job_id, "comfyui"
            state, finished = REATTACHED_STATES.get(found["status"], "running"), found["status"] in FINISHED_STATUSES
        else:
            prompt_id = (job.progress or {}).get("prompt_id")
            if job.kind != RUN_KIND or not prompt_id:
                raise RelayError(
                    "not_a_workflow_job", f"job {job_id} is a {job.kind} job, not a workflow run", kind=job.kind
                )
            state, finished, source = job.status.value, job.state.finished, "relay"
        if not finished:
            raise RelayError(
                "job_not_finished",
                f"job {job_id} is still {state}; wait for it with job_status(timeout_seconds=...)",
                retryable=True,
                state=state,
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
        # Fetching one file: size only that one. Listing: the first MAX_SIZED_FILES.
        sized = [
            i
            for i, f in enumerate(files)
            if (
                fetch in (f["filename"], f"{f['subfolder']}/{f['filename']}")
                if fetch is not None
                else i < MAX_SIZED_FILES
            )
        ]
        found = await asyncio.gather(*(relay.comfyui.view_size(_ref(files[i])) for i in sized), return_exceptions=True)
        sizes = {i: size for i, size in zip(sized, found, strict=True) if isinstance(size, int)}
        listed = [
            OutputFile(
                **f,
                size_bytes=sizes.get(i),
                mime_type=mimetypes.guess_type(f["filename"])[0],
                view_path="/view?" + urlencode(_ref(f)),
            )
            for i, f in enumerate(files)
        ]
        status = entry.get("status") if isinstance(entry.get("status"), dict) else {}
        view = OutputsView(
            job_id=job_id,
            prompt_id=prompt_id,
            job_state=state,
            source=source,
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


def _too_large(size: int) -> RelayError:
    return RelayError(
        "upload_too_large",
        f"the file is about {size} bytes; the most this server uploads is {MAX_UPLOAD_BYTES}",
        limit=MAX_UPLOAD_BYTES,
        size_bytes=size,
    )


def _workflow_upload_input(relay: Relay) -> Callable[..., Any]:
    uploads = asyncio.Semaphore(UPLOAD_CONCURRENCY)

    async def workflow_upload_input(
        filename: str = Field(description="The file name to store it as, such as photo.png. Directories are dropped"),
        content_base64: str = Field(
            description=f"The file's bytes, base64-encoded (a data: URL prefix and line breaks are accepted). At "
            f"most {MAX_UPLOAD_BYTES} bytes decoded.",
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
        payload = "".join(payload.split())  # base64 is often wrapped at 76 or 64 columns
        if len(payload) > MAX_UPLOAD_BASE64_CHARS:
            raise _too_large(len(payload) // 4 * 3)
        content_type = mimetypes.guess_type(clean)[0] or "application/octet-stream"
        async with uploads:  # the decoded bytes and their multipart copy exist for one upload at a time
            try:
                data = base64.b64decode(payload, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise RelayError("invalid_base64", f"content_base64 is not valid base64: {exc}") from None
            if not data:
                raise RelayError("empty_upload", "the file is empty")
            if len(data) > MAX_UPLOAD_BYTES:
                raise _too_large(len(data))
            stored = await relay.comfyui.upload_input(clean, data, content_type)
            size = len(data)
            del data
        _object_info.pop(relay.comfyui, None)  # LoadImage's file list just changed
        return Uploaded(
            name=stored["name"],
            subfolder=str(stored.get("subfolder") or ""),
            type=str(stored.get("type") or "input"),
            size_bytes=size,
            requested_name=clean,
            renamed=stored["name"] != clean,
        )

    return workflow_upload_input


# -- registration --------------------------------------------------------------


RUN = frozenset({"run"})

# (name, profiles, make, annotations), which tools.py wraps in its ToolSpec.
# Annotations are MCP hints; clients may show them, gate on them, or ignore them:
# - workflow_validate, workflow_outputs: read-only.
# - workflow_run: not read-only (it queues work and ComfyUI writes new output files), but not destructive either:
#   it replaces and deletes nothing (SaveImage numbers files, never overwrites). Not idempotent: each call is
#   another run with new outputs.
# - workflow_upload_input: not read-only (it adds a file to ComfyUI's input directory), not destructive (it never
#   overwrites: ComfyUI renames a clash), idempotent (the same bytes under the same name are stored once).
# All are closed-world as far as this server goes: they reach only the configured ComfyUI, and a graph with
# partner-API nodes is refused. What a custom node inside ComfyUI does is ComfyUI's (workflow_run says so).
WORKFLOW_TOOLS: tuple[tuple[str, frozenset[str], Callable[[Relay], Callable[..., Any]], ToolAnnotations], ...] = (
    (
        "workflow_validate",
        RUN,
        _workflow_validate,
        ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False),
    ),
    (
        "workflow_run",
        RUN,
        _workflow_run,
        ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False),
    ),
    (
        "workflow_outputs",
        RUN,
        _workflow_outputs,
        ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False),
    ),
    (
        "workflow_upload_input",
        RUN,
        _workflow_upload_input,
        ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False),
    ),
)
