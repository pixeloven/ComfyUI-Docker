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
from relay_helpers import TOKEN, comfyui_answering, serve_nothing, settings
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
    monkeypatch.setattr(uvicorn.Server, "serve", serve_nothing)
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
        ("http://u:p@[::1", "http://***@[::1"),
        ("http://[fe80::1%25eth0]:8188", "http://[fe80::1%25eth0]:8188"),
        ("http://u:p@[fe80::1%25eth0]:8188", "http://***@[fe80::1%25eth0]:8188"),
        ("http://ad%40min:pa%2Fss@comfyui:8188", "http://***@comfyui:8188"),
        # A password with an unencoded '/', '?' or '#': a URL parser ends the host
        # at that character, which leaves the '@' and the password outside it.
        ("http://admin:pa/ss@comfyui:8188", "http://***@comfyui:8188"),
        ("http://admin:12/ss@comfyui:8188", "http://***@comfyui:8188"),
        ("http://admin:8188?x@comfyui", "http://***@comfyui"),
        ("http://admin:88#x@comfyui", "http://***@comfyui"),
        ("admin:hunter2@comfyui:8188", "***@comfyui:8188"),
    ],
)
def test_redact_url(url, shown):
    assert redact_url(url) == shown


@pytest.mark.parametrize(
    ("url", "secret"),
    [
        ("http://admin:pa/ss@comfyui:8188", "pa/ss"),  # a "port" of `pa`: its parse error quoted it
        ("http://admin:12/ss@comfyui:8188", "12/ss"),  # used to validate as host admin, port 12
        ("http://admin:8188?x@comfyui", "8188?x"),
        ("http://admin:88#x@comfyui", "88#x"),
    ],
)
def test_an_at_sign_outside_the_host_is_refused_without_echoing_the_password(url, secret):
    with pytest.raises(ConfigError) as info:
        Settings.load(comfyui_url=url, host="h", port=1, profiles="read", env={TOKEN_ENV: TOKEN})
    message = str(info.value)
    assert "outside its host part" in message and "percent-encode" in message
    assert secret not in message and "admin" not in message


def test_percent_encoded_credentials_are_accepted():
    url = "http://admin:pa%2Fss%3Fx%23y@comfyui:8188"
    s = Settings.load(comfyui_url=url, host="h", port=1, profiles="read", env={TOKEN_ENV: TOKEN})
    assert s.comfyui_url == url


@pytest.mark.parametrize(
    ("url", "reason"),
    [("http://exämple..:8188", "Invalid IDNA hostname"), ("http://a:b@exämple..:8188", "Invalid IDNA hostname")],
)
def test_a_host_the_http_client_would_refuse_is_a_config_error(url, reason):
    with pytest.raises(ConfigError, match=reason) as info:
        Settings.load(comfyui_url=url, host="h", port=1, profiles="read", env={TOKEN_ENV: TOKEN})
    assert "a:b" not in str(info.value)


def test_an_idna_host_the_http_client_accepts_is_accepted():
    s = Settings.load(comfyui_url="http://exämple.com:8188", host="h", port=1, profiles="read", env={TOKEN_ENV: TOKEN})
    assert s.comfyui_url == "http://exämple.com:8188"


def test_the_settings_repr_hides_comfyui_url():
    assert "hunter2" not in repr(settings(comfyui_url="http://admin:hunter2@comfyui:8188"))


# -- the token must be sendable in a header ----------------------------------------


@pytest.mark.parametrize("token", ["abc\ndef", "abc def", "abc\tdef", "tökén", "abc\x00def", "abc\x7fdef"], ids=repr)
def test_a_token_that_cannot_be_sent_is_refused_without_echoing_it(token):
    with pytest.raises(ConfigError, match="cannot be sent in an HTTP header") as info:
        Settings.load(comfyui_url="http://x", host="h", port=1, profiles="read", env={TOKEN_ENV: token})
    assert "abc" not in str(info.value) and "tök" not in str(info.value)


def test_the_probe_refuses_a_token_with_a_line_break_without_printing_it(monkeypatch):
    """It used to send it: h11 raised `Illegal header value b'Bearer …'`, printing the token twice."""
    monkeypatch.setenv(TOKEN_ENV, "secret-part-one\nsecret-part-two")
    r = runner.invoke(app, ["relay", "probe", "http://127.0.0.1:9/mcp", "--timeout", "2"])
    assert r.exit_code == 2
    assert "cannot be sent in an HTTP header" in r.output
    assert "secret-part" not in r.output


def test_serve_refuses_a_token_with_a_line_break_without_printing_it(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, "secret-part-one\nsecret-part-two")
    r = runner.invoke(app, ["relay", "serve"])
    assert r.exit_code == 2
    assert "cannot be sent in an HTTP header" in r.output
    assert "secret-part" not in r.output


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
    monkeypatch.setattr(uvicorn.Server, "serve", serve_nothing)
    serve(settings(comfyui_url="http://admin:hunter2@comfyui:8188"))
    assert "ComfyUI at http://***@comfyui:8188" in caplog.text
    assert "hunter2" not in caplog.text


def test_a_config_error_does_not_echo_credentials():
    with pytest.raises(ConfigError) as info:
        Settings.load(
            comfyui_url="ftp://admin:hunter2@comfyui", host="h", port=1, profiles="read", env={TOKEN_ENV: TOKEN}
        )
    assert "ftp://***@comfyui" in str(info.value) and "hunter2" not in str(info.value)
