"""One async job mechanism for everything that outlives a tool call.

A workflow run, a node install, a dev reload: each is submitted as a job, gets
an id straight away, and is then followed with the `job_*` tools: `job_status`
(status, or wait with a timeout) and `job_cancel`. Producers never grow their
own polling tools.

A job is a coroutine the store runs as a task. Cancelling a job cancels that
task, so a producer that must undo something outside this process (asking
ComfyUI to interrupt a prompt, say) does it in its own
`except asyncio.CancelledError:` block and re-raises. A cancel waits at most
`cancel_wait` seconds for that; a job still unwinding after it reports
`cancelling`. The request is recorded, so a job whose cancel was requested
ends `cancelled` even if its producer swallows the CancelledError and returns.

At most `max_in_flight` jobs run at once (COMFYUI_MCP_MAX_JOBS); a submission
past that is refused with `too_many_jobs`, which is retryable.

The store is in memory. Jobs do not survive a restart, and an MCP session
ending does not cancel them: any session can follow any job by id. Finished
jobs are kept up to a limit, oldest dropped first, so a long-lived sidecar
does not grow without bound.
"""

from __future__ import annotations

import asyncio
import enum
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .errors import RelayError
from .settings import DEFAULT_MAX_JOBS

# How long one `wait` may hold a tool call open. MCP clients time calls out on
# their own, and an agent that needs longer calls `wait` again.
MAX_WAIT_SECONDS = 300.0
# How long a cancel waits for the producer to unwind before it answers
# `cancelling`. The job keeps unwinding; job_status shows when it has.
CANCEL_WAIT_SECONDS = 10.0
KEEP_FINISHED = 256


class JobState(str, enum.Enum):
    queued = "queued"
    running = "running"
    # Reported, never stored: a cancel was requested and the job has not stopped yet.
    cancelling = "cancelling"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"

    @property
    def finished(self) -> bool:
        return self in (JobState.succeeded, JobState.failed, JobState.cancelled)


@dataclass
class Job:
    id: str
    kind: str
    summary: str
    state: JobState = JobState.queued
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: Any = None
    error: dict[str, Any] | None = None
    cancel_requested: bool = False
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    @property
    def status(self) -> JobState:
        """The state to report: `cancelling` between a cancel request and the job stopping."""
        if self.cancel_requested and not self.state.finished:
            return JobState.cancelling
        return self.state

    def snapshot(self) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "kind": self.kind,
            "summary": self.summary,
            "state": self.status.value,
            "finished": self.state.finished,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
        }


def unknown_job(job_id: str) -> RelayError:
    return RelayError(
        "unknown_job",
        f"no job {job_id!r}: it never existed here, was dropped after finishing, "
        "or the server restarted (jobs are kept in memory)",
        job_id=job_id,
    )


class JobStore:
    def __init__(
        self,
        *,
        keep_finished: int = KEEP_FINISHED,
        max_in_flight: int = DEFAULT_MAX_JOBS,
        cancel_wait: float = CANCEL_WAIT_SECONDS,
    ) -> None:
        self._jobs: dict[str, Job] = {}
        self._keep_finished = keep_finished
        self.max_in_flight = max_in_flight
        self._cancel_wait = cancel_wait

    def submit(self, kind: str, work: Callable[[], Awaitable[Any]], *, summary: str = "") -> Job:
        """Start `work()` as a job and return it at once. Needs a running event loop.

        Raises `too_many_jobs` (retryable) when `max_in_flight` jobs have not finished.
        """
        in_flight = sum(1 for j in self._jobs.values() if not j.state.finished)
        if in_flight >= self.max_in_flight:
            raise RelayError(
                "too_many_jobs",
                f"{in_flight} jobs are already in flight, the most this server runs at once; "
                "wait for one to finish or cancel one, then submit again",
                retryable=True,
                limit=self.max_in_flight,
            )
        job = Job(id=uuid.uuid4().hex, kind=kind, summary=summary)
        self._jobs[job.id] = job
        job.task = asyncio.get_running_loop().create_task(self._run(job, work), name=f"job-{job.id}")
        job.task.add_done_callback(lambda _task: self._settle(job))
        self._prune()
        return job

    def get(self, job_id: str) -> Job:
        try:
            return self._jobs[job_id]
        except KeyError:
            raise unknown_job(job_id) from None

    async def wait(self, job_id: str, timeout: float) -> Job:
        """Return when the job finishes or `timeout` seconds pass, whichever is first.

        A timeout does not cancel the job; it only ends this wait.
        """
        job = self.get(job_id)
        timeout = min(max(timeout, 0.0), MAX_WAIT_SECONDS)
        if job.task is not None and not job.task.done():
            # asyncio.wait, not wait_for: it never cancels what it waits on.
            await asyncio.wait({job.task}, timeout=timeout)
        return job

    async def cancel(self, job_id: str) -> Job:
        """Cancel the job if it has not finished, and wait up to `cancel_wait` seconds for it to stop.

        A job still unwinding after that reports `cancelling`; it ends `cancelled`.
        """
        job = self.get(job_id)
        if job.task is not None and not job.task.done():
            job.cancel_requested = True
            job.task.cancel()
            await asyncio.wait({job.task}, timeout=self._cancel_wait)
        return job

    @staticmethod
    def _settle(job: Job) -> None:
        # A task cancelled before its first step never enters _run, so nothing
        # there recorded the outcome.
        if not job.state.finished:
            job.state = JobState.cancelled
            job.finished_at = time.time()

    async def _run(self, job: Job, work: Callable[[], Awaitable[Any]]) -> None:
        job.state = JobState.running
        job.started_at = time.time()
        try:
            job.result = await work()
            job.state = JobState.succeeded
        except asyncio.CancelledError:
            job.state = JobState.cancelled
            raise
        except RelayError as exc:
            job.state = JobState.failed
            job.error = exc.as_dict()
        except Exception as exc:  # a job's failure is its result, not the server's
            job.state = JobState.failed
            job.error = {"code": "job_failed", "message": f"{type(exc).__name__}: {exc}", "retryable": False}
        finally:
            # A producer may swallow the CancelledError and return, or fail while
            # unwinding. Either way it stopped because it was asked to.
            if job.cancel_requested:
                job.state = JobState.cancelled
            job.finished_at = time.time()

    def _prune(self) -> None:
        finished = [j for j in self._jobs.values() if j.state.finished]
        for job in finished[: max(0, len(finished) - self._keep_finished)]:
            del self._jobs[job.id]
