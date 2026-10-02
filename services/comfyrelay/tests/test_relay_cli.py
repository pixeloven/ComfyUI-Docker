"""`comfyctl relay serve|probe`: exit codes and output, through comfyctl's mount."""

from __future__ import annotations

import json
import logging

import pytest
from comfyctl.cli import app
from relay_helpers import TOKEN
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture(autouse=True)
def _restore_logging():
    """`serve` points the root logger at the stderr CliRunner provides, and
    closes after the call; later tests must not log into that closed stream."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def test_serve_refuses_to_start_without_a_token(monkeypatch):
    monkeypatch.delenv("COMFYUI_MCP_HTTP_TOKEN", raising=False)
    r = runner.invoke(app, ["relay", "serve"])
    assert r.exit_code == 2
    assert "Refusing to start: COMFYUI_MCP_HTTP_TOKEN is not set" in r.output


def test_serve_refuses_a_short_token_with_exit_2(monkeypatch):
    monkeypatch.setenv("COMFYUI_MCP_HTTP_TOKEN", "short-token")
    r = runner.invoke(app, ["relay", "serve"])
    assert r.exit_code == 2
    assert "Refusing to start: COMFYUI_MCP_HTTP_TOKEN is 11 characters" in r.output
    assert "openssl rand -hex 32" in r.output
    assert "short-token" not in r.output


def test_serve_refuses_an_unknown_profile(monkeypatch):
    monkeypatch.setenv("COMFYUI_MCP_HTTP_TOKEN", TOKEN)
    r = runner.invoke(app, ["relay", "serve", "--profiles", "read,admin"])
    assert r.exit_code == 2
    assert "unknown profile admin" in r.output


def test_serve_refuses_the_declined_develop_profile(monkeypatch):
    monkeypatch.setenv("COMFYUI_MCP_HTTP_TOKEN", TOKEN)
    monkeypatch.setenv("COMFYUI_MCP_PROFILES", "read,develop")
    r = runner.invoke(app, ["relay", "serve"])
    assert r.exit_code == 2
    assert "profile develop isn't available in this image" in r.output
    assert "https://github.com/pixeloven/ComfyUI-Docker/blob/main/docs/user-guides/developing-nodes.md" in r.output


def test_serve_logs_json_lines_with_o_json(monkeypatch):
    monkeypatch.delenv("COMFYUI_MCP_HTTP_TOKEN", raising=False)
    r = runner.invoke(app, ["relay", "serve", "-o", "json"])
    line = json.loads(r.output.strip().splitlines()[-1])
    assert line["level"] == "ERROR" and "Refusing to start" in line["message"]


def test_probe_needs_the_token(monkeypatch):
    monkeypatch.delenv("COMFYUI_MCP_HTTP_TOKEN", raising=False)
    r = runner.invoke(app, ["relay", "probe"])
    assert r.exit_code == 2


def test_probe_passes_against_a_running_server(live_server, monkeypatch):
    monkeypatch.setenv("COMFYUI_MCP_HTTP_TOKEN", TOKEN)
    r = runner.invoke(app, ["relay", "probe", live_server, "-o", "json"])
    assert r.exit_code == 0, r.output
    report = json.loads(r.stdout)
    assert report["ok"] is True
    assert [c["name"] for c in report["checks"]] == [
        "reachable",
        "auth",
        "token",
        "initialize",
        "tools",
        "server_info",
        "docs",
        "comfyui",
    ]
    assert report["docs_hits"] == 1
    assert report["tools"] == [
        "docs_guide",
        "docs_search",
        "job_cancel",
        "job_status",
        "model_list",
        "node_describe",
        "node_search",
        "server_info",
        "template_get",
        "template_search",
        "workflow_outputs",
        "workflow_run",
        "workflow_upload_input",
        "workflow_validate",
    ]
    assert report["server_info"]["comfyui"]["live_version"] == "0.37.0"


def test_probe_plain_output(live_server, monkeypatch):
    monkeypatch.setenv("COMFYUI_MCP_HTTP_TOKEN", TOKEN)
    r = runner.invoke(app, ["relay", "probe", live_server])
    assert r.exit_code == 0
    assert r.stdout.strip().splitlines()[-1] == f"probe: PASS {live_server}"


@pytest.mark.parametrize(
    ("token", "url_suffix", "failed"),
    [("wrong", "", "token"), (TOKEN, "-nothing-here", "initialize")],
)
def test_probe_fails_with_exit_1_and_says_which_check(live_server, monkeypatch, token, url_suffix, failed):
    monkeypatch.setenv("COMFYUI_MCP_HTTP_TOKEN", token)
    r = runner.invoke(app, ["relay", "probe", live_server + url_suffix, "-o", "json"])
    assert r.exit_code == 1
    report = json.loads(r.stdout)
    assert report["ok"] is False
    assert report["checks"][-1]["name"] == failed
    assert report["checks"][-1]["ok"] is False


def test_probe_fails_without_a_docs_index_unless_told_not_to_need_one(live_server_without_docs, monkeypatch):
    monkeypatch.setenv("COMFYUI_MCP_HTTP_TOKEN", TOKEN)
    r = runner.invoke(app, ["relay", "probe", live_server_without_docs, "-o", "json"])
    assert r.exit_code == 1
    failed = [c for c in json.loads(r.stdout)["checks"] if not c["ok"]]
    assert [c["name"] for c in failed] == ["docs"]
    assert "no docs index at" in failed[0]["detail"]
    r = runner.invoke(app, ["relay", "probe", live_server_without_docs, "--no-docs"])
    assert r.exit_code == 0, r.stdout


def test_probe_fails_when_nothing_listens(monkeypatch):
    monkeypatch.setenv("COMFYUI_MCP_HTTP_TOKEN", TOKEN)
    r = runner.invoke(app, ["relay", "probe", "http://127.0.0.1:9/mcp", "--timeout", "2"])
    assert r.exit_code == 1
    assert "FAIL  reachable" in r.stdout
