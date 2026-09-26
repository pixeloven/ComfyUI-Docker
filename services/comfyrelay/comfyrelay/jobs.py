"""One async job mechanism for everything that outlives a tool call.

A workflow run, a node install, a dev reload: each is submitted as a job, gets
an id straight away, and is then followed with the `job_*` tools: `job_status`
(status, or wait with a timeout) and `job_cancel`. Producers never grow their
own polling tools.

THE PRODUCER CONTRACT. A job is a coroutine the store runs as a task, and
cancelling a job cancels that task. A producer MUST let `CancelledError`
propagate, re-raising it within `cancel_wait` seconds (CANCEL_WAIT_SECONDS).
One that must undo something outside this process (asking ComfyUI to
interrupt a prompt, say) does it in its own `except asyncio.CancelledError:`
block, bounded in time, and re-raises. Every producer's tests call
`tests/relay_helpers.py: assert_producer_honours_cancel`.

What the store does when a producer breaks the contract:
- A job still running after its cancel deadline reports `cancelling`, and the
  store logs an error naming it. It keeps its slot until it stops.
- A job whose cancel was requested ends `cancelled`, even if its producer
  swallows the CancelledError and returns. A cancelled job has no `result`:
  whatever such a producer returned is dropped, because it was cut short.
- On shutdown every job is cancelled, and the wait for them is bounded, so a
  stuck producer cannot keep the server from exiting (server.run_until_stopped).

At most `max_in_flight` jobs run at once (COMFYUI_MCP_MAX_JOBS); a submission
past that is refused with `too_many_jobs`. It is retryable, unless every slot
is held by a job that overran its cancel deadline: those may never free, so
only a restart helps.

The store is in memory. Jobs do not survive a restart, and an MCP session
ending does not cancel them: any session can follow any job by id. Finished
jobs are kept up to a limit, oldest dropped first, so a long-lived sidecar
does not grow without bound.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .errors import RelayError
from .settings import DEFAULT_MAX_JOBS

log = logging.getLogger("comfyrelay.jobs")

# How long one `wait` may hold a tool call open. MCP clients time calls out on
# their own, and an agent that needs longer calls `wait` again.
MAX_WAIT_SECONDS = 300.0
# How long a producer has to stop once cancelled (the producer contract), and
# so how long a cancel waits before it answers `cancelling`.
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
    # When a cancel was first requested (time.monotonic()), or None.
    cancel_requested_at: float | None = None
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    @property
    def cancel_requested(self) -> bool:
        return self.cancel_requested_at is not None

    @property
    def status(self) -> JobState:
        """The state to report: `cancelling` between a cancel request and the job stopping."""
        if self.cancel_requested and not self.state.finished:
            return JobState.cancelling
        return self.state

    def overran(self, cancel_wait: float) -> bool:
        """Still running more than `cancel_wait` seconds after it was cancelled."""
        return (
            self.cancel_requested_at is not None
            and not self.state.finished
            and time.monotonic() - self.cancel_requested_at > cancel_wait
        )

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

        Raises `too_many_jobs` when `max_in_flight` jobs have not finished. It is
        retryable unless every one of them overran its cancel deadline.
        """
        live = [j for j in self._jobs.values() if not j.state.finished]
        if len(live) >= self.max_in_flight:
            cancelling = sum(1 for j in live if j.cancel_requested)
            stuck = sum(1 for j in live if j.overran(self._cancel_wait))
            if stuck == len(live):
                message = (
                    f"all {len(live)} job slots are held by jobs that did not stop when cancelled; they may "
                    "never free, so retrying will not help. Restart the server"
                )
            else:
                message = (
                    f"{len(live)} jobs are already in flight, the most this server runs at once; "
                    "wait for one to finish or cancel one, then submit again"
                )
            raise RelayError(
                "too_many_jobs",
                message,
                retryable=stuck < len(live),
                limit=self.max_in_flight,
                in_flight=len(live),
                cancelling=cancelling,
                stuck=stuck,
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

        A job still unwinding after that reports `cancelling`, and is logged as
        breaking the producer contract; it ends `cancelled` when it stops.
        """
        job = self.get(job_id)
        if self._request_cancel(job):
            await asyncio.wait({job.task}, timeout=self._cancel_wait)
            if not job.task.done():
                self._log_overrun(job)
        return job

    async def shutdown(self, wait: float = CANCEL_WAIT_SECONDS) -> list[Job]:
        """Cancel every unfinished job and wait up to `wait` seconds for them all.

        Returns the jobs that did not stop, each logged. Nothing here waits longer.
        """
        live = [j for j in self._jobs.values() if self._request_cancel(j)]
        if live:
            log.info("shutting down: cancelling %d job(s)", len(live))
            await asyncio.wait({j.task for j in live}, timeout=wait)
        stuck = [j for j in live if not j.task.done()]
        for job in stuck:
            self._log_overrun(job)
        return stuck

    def _request_cancel(self, job: Job) -> bool:
        """Cancel the job's task if it is still running. True if it was."""
        if job.task is None or job.task.done():
            return False
        if job.cancel_requested_at is None:
            job.cancel_requested_at = time.monotonic()
        job.task.cancel()
        return True

    @staticmethod
    def _log_overrun(job: Job) -> None:
        log.error(
            "job %s (%s) did not stop within %.0fs of being cancelled: its producer must re-raise "
            "CancelledError (the producer contract in comfyrelay/jobs.py). It holds a job slot until it stops.",
            job.id,
            job.kind,
            time.monotonic() - (job.cancel_requested_at or time.monotonic()),
        )

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
            # unwinding. Either way it stopped because it was asked to, and what
            # it returned is not a complete result.
            if job.cancel_requested:
                job.state = JobState.cancelled
                job.result = None
            job.finished_at = time.time()

    def _prune(self) -> None:
        finished = [j for j in self._jobs.values() if j.state.finished]
        for job in finished[: max(0, len(finished) - self._keep_finished)]:
            del self._jobs[job.id]
