"""The job mechanism, with fake jobs (nothing produces real ones until workflow
runs arrive), and the `job_status` and `job_cancel` tools that follow them."""

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


# -- robustness: bounded cancel, a recorded cancel, a cap on jobs in flight --


async def test_cancel_waits_a_bounded_time_and_reports_cancelling():
    """A producer slow to unwind does not hold the cancel call open."""
    store = JobStore(cancel_wait=0.05)
    release = asyncio.Event()

    async def slow_to_unwind():
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            await release.wait()  # cleanup that takes a while (asking ComfyUI to interrupt, say)
            raise

    job = store.submit("test.fake", slow_to_unwind)
    await asyncio.sleep(0)
    answered = await asyncio.wait_for(store.cancel(job.id), 5)
    assert answered.snapshot()["state"] == "cancelling"
    assert answered.snapshot()["finished"] is False
    release.set()
    done = await store.wait(job.id, 5)
    assert done.snapshot()["state"] == "cancelled" and done.snapshot()["finished"] is True


async def test_a_producer_that_swallows_the_cancel_still_ends_cancelled():
    store = JobStore()

    async def swallows():
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            return "pretended to finish"

    job = store.submit("test.fake", swallows)
    await asyncio.sleep(0)
    cancelled = await store.cancel(job.id)
    assert cancelled.state is JobState.cancelled
    assert cancelled.snapshot()["state"] == "cancelled"


async def test_a_producer_that_swallows_the_cancel_and_keeps_going_is_cancelling_until_it_stops():
    store = JobStore(cancel_wait=0.05)
    stop = asyncio.Event()

    async def keeps_going():
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass
        await stop.wait()
        return "done anyway"

    job = store.submit("test.fake", keeps_going)
    await asyncio.sleep(0)
    assert (await store.cancel(job.id)).snapshot()["state"] == "cancelling"
    stop.set()
    assert (await store.wait(job.id, 5)).snapshot()["state"] == "cancelled"


async def test_jobs_in_flight_are_capped():
    store = JobStore(max_in_flight=2)
    first = store.submit("t", lambda: asyncio.sleep(30))
    store.submit("t", lambda: asyncio.sleep(30))
    with pytest.raises(RelayError) as info:
        store.submit("t", lambda: asyncio.sleep(30))
    assert info.value.code == "too_many_jobs"
    assert info.value.retryable is True
    assert info.value.detail == {"limit": 2}
    await store.cancel(first.id)  # a finished job frees its slot
    store.submit("t", lambda: asyncio.sleep(30))
    for job_id in list(store._jobs):
        await store.cancel(job_id)


def test_the_cap_comes_from_the_environment():
    from comfyrelay.settings import TOKEN_ENV, ConfigError, Settings

    def load(env):
        return Settings.load(comfyui_url="http://x", host="h", port=1, profiles="run", env={TOKEN_ENV: "t", **env})

    assert load({}).max_jobs == 16
    assert load({"COMFYUI_MCP_MAX_JOBS": "4"}).max_jobs == 4
    for bad in ("0", "-1", "many", "2.5"):
        with pytest.raises(ConfigError, match="COMFYUI_MCP_MAX_JOBS"):
            load({"COMFYUI_MCP_MAX_JOBS": bad})


# -- the tools: job_status reads, job_cancel stops --------------------------


async def test_job_tools_are_annotated_honestly():
    server, _ = build_server(settings(), comfyui=comfyui_answering())
    async with Client(server, mode="legacy") as client:
        tools = {t.name: t.annotations for t in (await client.list_tools()).tools}
    assert tools["job_status"].read_only_hint is True
    assert tools["job_status"].destructive_hint is False
    assert tools["job_cancel"].read_only_hint is False
    assert tools["job_cancel"].destructive_hint is True
    assert "job" not in tools


@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_job_status_and_job_cancel(mode):
    server, relay = build_server(settings(), comfyui=comfyui_answering())
    gate = asyncio.Event()

    async def work():
        await gate.wait()
        return "ok"

    async with Client(server, mode=mode) as client:
        quick = relay.jobs.submit("test.fake", work, summary="finishes when told")
        slow = relay.jobs.submit("test.fake", lambda: asyncio.sleep(30))

        status = await client.call_tool("job_status", {"job_id": quick.id})
        assert status.structured_content["state"] in ("queued", "running")

        gate.set()
        waited = await client.call_tool("job_status", {"job_id": quick.id, "timeout_seconds": 5})
        assert waited.structured_content["state"] == "succeeded"
        assert waited.structured_content["result"] == "ok"
        assert waited.structured_content["summary"] == "finishes when told"

        cancelled = await client.call_tool("job_cancel", {"job_id": slow.id})
        assert cancelled.structured_content["state"] == "cancelled"
        again = await client.call_tool("job_cancel", {"job_id": quick.id})
        assert again.structured_content["state"] == "succeeded"  # finished: nothing to cancel


@pytest.mark.parametrize(("tool", "args"), [("job_status", {"timeout_seconds": 1}), ("job_cancel", {})])
async def test_job_tools_unknown_id_is_a_structured_error(tool, args):
    server, _ = build_server(settings(), comfyui=comfyui_answering())
    async with Client(server, mode="legacy") as client:
        result = await client.call_tool(tool, {"job_id": "nope", **args})
    assert result.is_error
    text = result.content[0].text
    assert text.startswith(f"Error executing tool {tool}: {{")  # the SDK's prefix, then ours
    error = json.loads(text[text.index("{") :])["error"]
    assert error["code"] == "unknown_job" and error["retryable"] is False


async def test_job_status_rejects_a_wait_over_the_cap():
    server, _ = build_server(settings(), comfyui=comfyui_answering())
    async with Client(server, mode="legacy") as client:
        result = await client.call_tool("job_status", {"job_id": "x", "timeout_seconds": 10_000})
    assert result.is_error
