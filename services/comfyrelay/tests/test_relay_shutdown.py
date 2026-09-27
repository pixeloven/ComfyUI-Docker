"""Stopping: a real `comfyctl relay serve` in a subprocess, stopped by a real signal.

uvicorn catches SIGTERM and SIGINT while it serves, shuts down, and then
re-raises the signal with its original handler. For SIGTERM that handler is
the default, so the process dies right there: anything that runs after
uvicorn's `serve()` returns never runs on a SIGTERM. These tests use real
signals, and nothing in uvicorn is patched but its startup hook, where the
jobs are submitted.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import pytest
from relay_helpers import TOKEN, free_port

# Starts the relay the way the image does (`comfyctl relay serve`). Once it
# listens, it submits a job whose producer honours the cancel, writing a marker
# file as its cleanup, and with `stuck`, one that never stops. Then it prints
# READY and waits for the signal.
SERVE = """
import asyncio, pathlib, sys
import uvicorn
import comfyctl.cli
import comfyrelay.server as server_mod

marker = pathlib.Path(sys.argv[1])
stuck = sys.argv[2] == "stuck"
relays = []
real_build = server_mod.build_server

def build(settings, **kw):
    server, relay = real_build(settings, **kw)
    relays.append(relay)
    return server, relay

async def good():
    try:
        await asyncio.sleep(3600)
    except asyncio.CancelledError:
        marker.write_text("cleaned up")
        raise

async def stubborn():
    while True:
        try:
            await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            pass

real_startup = uvicorn.Server.startup

async def startup(self, sockets=None):
    await real_startup(self, sockets)
    relays[0].jobs.submit("test.good", good)
    if stuck:
        relays[0].jobs.submit("test.stuck", stubborn)
    await asyncio.sleep(0.05)
    print("READY", flush=True)

server_mod.build_server = build
uvicorn.Server.startup = startup
sys.argv = ["comfyctl", "relay", "serve"]
comfyctl.cli.main()
"""


def _stop(sig: int, stuck: bool, tmp_path) -> tuple[subprocess.CompletedProcess, float, bool]:
    marker = tmp_path / "cleaned-up"
    env = {
        **os.environ,
        "COMFYUI_MCP_HTTP_TOKEN": TOKEN,
        "COMFYUI_URL": "http://127.0.0.1:9",
        "MCP_HOST": "127.0.0.1",
        "MCP_PORT": str(free_port()),
        "COMFYUI_MCP_INSTANCE_ID": "shutdown-test",
    }
    # cwd is not services/: `-c` puts the cwd on sys.path (see test_relay_secrets).
    proc = subprocess.Popen(
        [sys.executable, "-c", SERVE, str(marker), "stuck" if stuck else "good"],
        env=env,
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "READY", proc.stderr.read()
        t0 = time.monotonic()
        proc.send_signal(sig)
        out, err = proc.communicate(timeout=30)
        elapsed = time.monotonic() - t0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err), elapsed, marker.exists()


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT], ids=["SIGTERM", "SIGINT"])
def test_a_stop_cancels_every_job_and_runs_its_cleanup(sig, tmp_path):
    result, elapsed, cleaned_up = _stop(sig, stuck=False, tmp_path=tmp_path)
    assert cleaned_up, f"the job's cleanup never ran (exit {result.returncode}):\n{result.stderr}"
    assert "shutting down: cancelling 1 job(s)" in result.stderr
    assert elapsed < 5, elapsed
    print(f"{sig.name} with a good producer: exit {result.returncode} in {elapsed:.2f}s")


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT], ids=["SIGTERM", "SIGINT"])
def test_a_stuck_producer_cannot_hold_a_stop_past_the_grace_period(sig, tmp_path):
    """Docker and Kubernetes send SIGKILL 10s after SIGTERM by default."""
    result, elapsed, cleaned_up = _stop(sig, stuck=True, tmp_path=tmp_path)
    assert cleaned_up, f"the good job's cleanup never ran (exit {result.returncode}):\n{result.stderr}"
    assert "(test.stuck) did not stop within" in result.stderr
    assert result.stderr.count("(test.stuck) did not stop within") == 1  # logged once, not per pass
    assert elapsed < 10, elapsed
    print(f"{sig.name} with a stuck producer: exit {result.returncode} in {elapsed:.2f}s")
