"""comfyctl's contract: groups are mounted, never reimplemented, and share one set
of conventions.

The fetch group's behaviour is tested in depth by services/fetch/tests against
comfyfetch's app. These tests prove the mount passes it through untouched, so
the same flags give the same stdout and exit code under `comfyctl fetch`.
"""

from __future__ import annotations

import importlib.metadata
import pathlib

import pytest
import typer
from comfyctl.cli import app
from comfyfetch.cli import app as fetch_app
from typer.testing import CliRunner

FIXTURES = pathlib.Path(__file__).parents[2] / "fetch" / "tests" / "fixtures"
runner = CliRunner()


def test_every_comfyfetch_verb_is_under_fetch():
    """A verb added to comfyfetch appears under `comfyctl fetch` with no edit here."""
    fetch_group = typer.main.get_command(app).commands["fetch"]
    assert set(fetch_group.commands) == set(typer.main.get_command(fetch_app).commands)
    assert {"build", "resolve", "fetch", "check", "facts"} <= set(fetch_group.commands)


@pytest.mark.parametrize(
    "args",
    [
        ["check", "manifest-for-lock-good.yaml", "lock-good.yaml"],
        ["check", "manifest-for-lock-good.yaml", "lock-good.yaml", "-o", "json"],
        ["check", "manifest-for-lock-good.yaml", "lock-no-hash.yaml"],
        ["check", "missing.yaml", "lock-good.yaml"],
        [
            "resolve",
            "manifest-two-profiles.yaml",
            "--profile",
            "just-a",
            "--from-lock",
            "lock-two-entries.yaml",
        ],
        [
            "resolve",
            "manifest-two-profiles.yaml",
            "--from-lock",
            "lock-two-entries.yaml",
        ],
        ["fetch", "lock-good.yaml", "{tmp}", "-o", "json"],
        ["fetch", "lock-good.yaml", "{tmp}"],
        ["build", "missing-dir"],
    ],
)
def test_fetch_group_matches_comfyfetch(args, tmp_path, monkeypatch):
    """Same stdout, same exit code, whichever way the app is reached."""
    monkeypatch.chdir(FIXTURES)
    args = [a.replace("{tmp}", str(tmp_path)) for a in args]
    direct = runner.invoke(fetch_app, args)
    mounted = runner.invoke(app, ["fetch", *args])
    assert (mounted.exit_code, mounted.stdout) == (direct.exit_code, direct.stdout)


def test_every_command_takes_the_one_output_flag():
    """One convention for every group: --output/-o auto|plain|json."""

    # Typer vendors its click, so a group is recognised by shape, not by class.
    def leaves(cmd, path: str):
        if hasattr(cmd, "commands"):
            for name, sub in cmd.commands.items():
                yield from leaves(sub, f"{path} {name}")
        else:
            yield path, cmd

    for path, cmd in leaves(typer.main.get_command(app), "comfyctl"):
        opts = {p.name: p for p in cmd.params}
        assert "output" in opts, f"{path} has no --output"
        assert {"--output", "-o"} == set(opts["output"].opts), path
        assert list(opts["output"].type.choices) == ["auto", "plain", "json"], path


def test_version_is_reportable():
    r = runner.invoke(app, ["--version"])
    assert r.exit_code == 0
    assert r.stdout.strip() == importlib.metadata.version("comfyctl")


def test_no_args_shows_help_rather_than_a_traceback():
    assert "Usage" in runner.invoke(app, []).output
