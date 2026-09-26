"""Secrets stay secret: the token never appears in server_info, the probe's
output, the logs or a traceback, and credentials in COMFYUI_URL are sent to
ComfyUI but never rendered."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys

import httpx2
import pytest
import uvicorn
from comfyctl.cli import app
from comfyrelay.server import build_server, serve
from comfyrelay.settings import TOKEN_ENV, ConfigError, Settings, redact_url
from mcp import Client
from relay_helpers import TOKEN, comfyui_answering, settings
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture(autouse=True)
def _restore_logging():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def test_the_settings_repr_hides_the_token():
    assert TOKEN not in repr(settings())
    assert TOKEN not in str(settings())


@pytest.mark.anyio
async def test_server_info_never_carries_the_token():
    server, _ = build_server(settings(), comfyui=comfyui_answering())
    async with Client(server, mode="legacy") as client:
        result = await client.call_tool("server_info", {})
    assert TOKEN not in json.dumps(result.structured_content)
    assert all(TOKEN not in getattr(c, "text", "") for c in result.content)


@pytest.mark.parametrize("output", [[], ["-o", "json"]], ids=["plain", "json"])
def test_the_probe_never_prints_the_token(live_server, monkeypatch, output):
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    r = runner.invoke(app, ["relay", "probe", live_server, *output])
    assert r.exit_code == 0, r.output
    assert TOKEN not in r.output


def test_the_logs_never_carry_the_token(live_server, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(uvicorn.Server, "run", lambda self: None)
    serve(settings(instance_id_source="hostname"))  # the startup lines, and the hostname warning
    httpx2.post(live_server, json={}, headers={"Authorization": f"Bearer {TOKEN}x"})  # a 401, logged
    assert "on http://127.0.0.1:9000/mcp" in caplog.text and "401 for POST /mcp" in caplog.text
    assert TOKEN not in caplog.text
    # A refused start. `serve` points logging at its own stderr, so read that.
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    r = runner.invoke(app, ["relay", "serve", "--profiles", "nope"])
    assert "unknown profile nope" in r.output
    assert TOKEN not in r.output


# Run in a subprocess, because Typer prints its traceback from sys.excepthook.
# Typer's default is forced to what it was before 0.23 (show locals), so this
# fails on any Typer if an app stops turning locals off itself.
CRASH = """
import sys, typer
typer.Typer.__init__.__kwdefaults__["pretty_exceptions_show_locals"] = True
import comfyctl.cli, comfyrelay.server

def crash(settings):
    token = settings.token  # a local holding the token, in the frame that raises
    raise RuntimeError("forced crash")

comfyrelay.server.serve = crash
if sys.argv[1] == "control":
    comfyctl.cli.app.pretty_exceptions_show_locals = True
sys.argv = ["comfyctl", "relay", "serve"]
comfyctl.cli.main()
"""


@pytest.mark.parametrize("variant", ["as-shipped", "control"])
def test_a_crash_never_prints_the_token(variant, tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "_TYPER_STANDARD_TRACEBACK"}
    env.update({TOKEN_ENV: TOKEN, "COLUMNS": "200"})
    # cwd is not services/: `-c` puts the cwd on sys.path, where services/comfyrelay
    # would import as a namespace package ahead of the editable install.
    r = subprocess.run(
        [sys.executable, "-c", CRASH, variant],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert r.returncode == 1
    assert "forced crash" in r.stderr
    if variant == "control":  # proves the check can see a leak
        assert TOKEN in r.stderr
    else:
        assert TOKEN not in r.stdout + r.stderr


def test_a_malformed_comfyui_url_exits_2_without_a_traceback(monkeypatch):
    """The reviewer's crash: `http://[::1` used to reach httpx2 and print a traceback."""
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    r = runner.invoke(app, ["relay", "serve", "--comfyui-url", "http://[::1"])
    assert r.exit_code == 2
    assert "COMFYUI_URL" in r.output and "is not a valid URL" in r.output
    assert TOKEN not in r.output


# -- credentials in COMFYUI_URL -------------------------------------------------


@pytest.mark.parametrize(
    ("url", "shown"),
    [
        ("http://admin:hunter2@comfyui:8188", "http://***@comfyui:8188"),
        ("https://token@comfyui/base", "https://***@comfyui/base"),
        ("http://a:b@c@comfyui:8188/", "http://***@comfyui:8188/"),
        ("http://comfyui:8188", "http://comfyui:8188"),
        ("http://[::1", "http://[::1"),
        ("http://u:p@[::1", "<unparseable URL>"),
    ],
)
def test_redact_url(url, shown):
    assert redact_url(url) == shown


@pytest.mark.anyio
async def test_server_info_does_not_echo_credentials():
    """The reviewer's case: `http://admin:hunter2@…` came back in comfyui.error.message."""
    s = settings(comfyui_url="http://admin:hunter2@127.0.0.1:9")
    server, _ = build_server(s)  # a real client: nothing listens on port 9
    async with Client(server, mode="legacy") as client:
        got = (await client.call_tool("server_info", {})).structured_content
    assert got["comfyui"]["error"]["code"] == "comfyui_unreachable"
    assert "http://***@127.0.0.1:9" in got["comfyui"]["error"]["message"]
    assert "hunter2" not in json.dumps(got) and "admin" not in json.dumps(got)


def test_the_startup_log_does_not_echo_credentials(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="comfyrelay")
    monkeypatch.setattr(uvicorn.Server, "run", lambda self: None)
    serve(settings(comfyui_url="http://admin:hunter2@comfyui:8188"))
    assert "ComfyUI at http://***@comfyui:8188" in caplog.text
    assert "hunter2" not in caplog.text


def test_a_config_error_does_not_echo_credentials():
    with pytest.raises(ConfigError) as info:
        Settings.load(
            comfyui_url="ftp://admin:hunter2@comfyui", host="h", port=1, profiles="read", env={TOKEN_ENV: TOKEN}
        )
    assert "ftp://***@comfyui" in str(info.value) and "hunter2" not in str(info.value)
