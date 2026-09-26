"""The job mechanism, with fake jobs (nothing produces real ones until workflow
runs arrive), and the `job` tool that follows them."""

from __future__ import annotations

import asyncio
import json

import pytest
from comfyrelay.errors import RelayError
from comfyrelay.jobs import MAX_WAIT_SECONDS, JobState, JobStore
from comfyrelay.server import build_server
from mcp import Client
from relay_helpers import comfyui_answering, settings

pytestmark = pytest.mark.anyio


async def test_submit_returns_at_once_and_wait_gets_the_result():
    store = JobStore()
    gate = asyncio.Event()

    async def work():
        await gate.wait()
        return {"images": 1}

    job = store.submit("test.fake", work, summary="a fake job")
    await asyncio.sleep(0)
    assert store.get(job.id).state is JobState.running
    gate.set()
    done = await store.wait(job.id, 5)
    assert done.state is JobState.succeeded
    assert done.result == {"images": 1}
    assert done.snapshot()["finished"] is True
    assert done.started_at is not None and done.finished_at >= done.started_at


async def test_wait_times_out_without_cancelling():
    store = JobStore()
    job = store.submit("test.fake", lambda: asyncio.sleep(30))
    waited = await store.wait(job.id, 0.05)
    assert waited.state is JobState.running
    assert not job.task.cancelled()
    await store.cancel(job.id)


async def test_wait_is_capped(monkeypatch):
    store = JobStore()
    seen = {}

    async def fake_wait(tasks, timeout):
        seen["timeout"] = timeout

    job = store.submit("test.fake", lambda: asyncio.sleep(30))
    monkeypatch.setattr(asyncio, "wait", fake_wait)
    await store.wait(job.id, 10_000)
    monkeypatch.undo()
    assert seen["timeout"] == MAX_WAIT_SECONDS
    await store.cancel(job.id)


async def test_cancel_stops_a_running_job():
    store = JobStore()
    cleaned_up = asyncio.Event()

    async def work():
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cleaned_up.set()  # where a producer would ask ComfyUI to interrupt
            raise

    job = store.submit("test.fake", work)
    await asyncio.sleep(0)
    cancelled = await store.cancel(job.id)
    assert cancelled.state is JobState.cancelled
    assert cleaned_up.is_set()
    assert cancelled.finished_at is not None


async def test_cancel_before_the_job_starts():
    store = JobStore()
    job = store.submit("test.fake", lambda: asyncio.sleep(30))
    cancelled = await store.cancel(job.id)  # no await since submit: the task never ran
    assert cancelled.state is JobState.cancelled
    assert cancelled.finished_at is not None


async def test_cancel_of_a_finished_job_changes_nothing():
    store = JobStore()
    job = store.submit("test.fake", lambda: asyncio.sleep(0, result="done"))
    await store.wait(job.id, 5)
    assert (await store.cancel(job.id)).state is JobState.succeeded


async def test_failures_are_recorded_not_raised():
    store = JobStore()

    async def structured():
        raise RelayError("comfyui_unreachable", "gone", retryable=True)

    async def crash():
        raise ValueError("bad graph")

    a = await store.wait(store.submit("t", structured).id, 5)
    b = await store.wait(store.submit("t", crash).id, 5)
    assert a.state is JobState.failed and a.error["code"] == "comfyui_unreachable" and a.error["retryable"]
    assert b.state is JobState.failed and b.error == {
        "code": "job_failed",
        "message": "ValueError: bad graph",
        "retryable": False,
    }


async def test_unknown_job_is_a_structured_error():
    with pytest.raises(RelayError) as info:
        JobStore().get("nope")
    assert info.value.code == "unknown_job"


async def test_finished_jobs_are_pruned_oldest_first():
    store = JobStore(keep_finished=2)
    ids = []
    for _ in range(4):
        job = store.submit("t", lambda: asyncio.sleep(0))
        await store.wait(job.id, 5)
        ids.append(job.id)
    store.submit("t", lambda: asyncio.sleep(0))  # pruning happens on submit
    with pytest.raises(RelayError):
        store.get(ids[0])
    assert store.get(ids[3]).state is JobState.succeeded


# -- the tool ---------------------------------------------------------------


@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_job_tool_status_wait_cancel(mode):
    server, relay = build_server(settings(), comfyui=comfyui_answering())
    gate = asyncio.Event()

    async def work():
        await gate.wait()
        return "ok"

    async with Client(server, mode=mode) as client:
        quick = relay.jobs.submit("test.fake", work, summary="finishes when told")
        slow = relay.jobs.submit("test.fake", lambda: asyncio.sleep(30))

        status = await client.call_tool("job", {"job_id": quick.id})
        assert status.structured_content["state"] in ("queued", "running")

        gate.set()
        waited = await client.call_tool("job", {"job_id": quick.id, "action": "wait", "timeout_seconds": 5})
        assert waited.structured_content["state"] == "succeeded"
        assert waited.structured_content["result"] == "ok"
        assert waited.structured_content["summary"] == "finishes when told"

        cancelled = await client.call_tool("job", {"job_id": slow.id, "action": "cancel"})
        assert cancelled.structured_content["state"] == "cancelled"


async def test_job_tool_unknown_id_is_a_structured_error():
    server, _ = build_server(settings(), comfyui=comfyui_answering())
    async with Client(server, mode="legacy") as client:
        result = await client.call_tool("job", {"job_id": "nope", "action": "wait"})
    assert result.is_error
    text = result.content[0].text
    assert text.startswith("Error executing tool job: {")  # the SDK's prefix, then ours
    error = json.loads(text[text.index("{") :])["error"]
    assert error["code"] == "unknown_job" and error["retryable"] is False


async def test_job_tool_rejects_a_wait_over_the_cap():
    server, _ = build_server(settings(), comfyui=comfyui_answering())
    async with Client(server, mode="legacy") as client:
        result = await client.call_tool("job", {"job_id": "x", "action": "wait", "timeout_seconds": 10_000})
    assert result.is_error
