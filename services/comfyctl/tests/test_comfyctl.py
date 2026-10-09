"""comfyctl's contract: groups are mounted, never reimplemented, and share one set
of conventions.

The fetch group's behaviour is tested in depth by the other tests here, against
comfyctl.fetch's own app. These tests prove the mount passes it through untouched,
so the same flags give the same stdout and exit code under `comfyctl fetch`.
"""

from __future__ import annotations

import importlib.metadata
import pathlib

import pytest
import typer
from comfyctl.cli import app
from comfyctl.fetch.cli import app as fetch_app
from typer.testing import CliRunner

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
runner = CliRunner()


def test_every_fetch_verb_is_under_comfyctl_fetch():
    """A verb added to comfyctl.fetch appears under `comfyctl fetch` with no edit here."""
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
def test_fetch_group_matches_its_own_app(args, tmp_path, monkeypatch):
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


def test_relay_is_comfyrelays_app_when_installed():
    """In the workspace comfyrelay is installed, so `relay` is its app, mounted as-is."""
    from comfyrelay.cli import app as relay_app

    relay = typer.main.get_command(app).commands["relay"]
    assert set(relay.commands) == set(typer.main.get_command(relay_app).commands) == {"serve", "probe", "docs"}


def _hide_comfyrelay_distribution(monkeypatch):
    real = importlib.metadata.distribution

    def distribution(name):
        if name == "comfyrelay":
            raise importlib.metadata.PackageNotFoundError(name)
        return real(name)

    monkeypatch.setattr(importlib.metadata, "distribution", distribution)


@pytest.fixture
def comfyctl_without_comfyrelay(monkeypatch):
    """comfyctl.cli as a released wheel loads it: with no comfyrelay installed."""
    import importlib

    import comfyctl.cli

    _hide_comfyrelay_distribution(monkeypatch)
    yield importlib.reload(comfyctl.cli)
    monkeypatch.undo()
    importlib.reload(comfyctl.cli)


@pytest.fixture
def comfyctl_beside_a_stray_comfyrelay_dir(monkeypatch, tmp_path):
    """No comfyrelay installed, but a directory of that name on sys.path, as with
    `PYTHONPATH=services` or a `python -m` run from services/: it imports as an
    empty namespace package, with no `comfyrelay.cli` in it."""
    import importlib
    import importlib.machinery
    import importlib.util
    import sys

    import comfyctl.cli

    (tmp_path / "comfyrelay").mkdir()

    class StrayFirst:
        """Resolves `comfyrelay` and its submodules from tmp_path only, as if the
        installed one were absent (the editable install's finder would otherwise
        find `comfyrelay.cli` by name)."""

        @staticmethod
        def find_spec(name, path=None, target=None):
            if name != "comfyrelay" and not name.startswith("comfyrelay."):
                return None
            spec = importlib.machinery.PathFinder.find_spec(name, [str(tmp_path)] if name == "comfyrelay" else path)
            if spec is None:
                raise ModuleNotFoundError(f"No module named {name!r}", name=name)
            return spec

    _hide_comfyrelay_distribution(monkeypatch)
    monkeypatch.setattr(sys, "meta_path", [StrayFirst, *sys.meta_path])
    for name in [m for m in sys.modules if m == "comfyrelay" or m.startswith("comfyrelay.")]:
        monkeypatch.delitem(sys.modules, name)
    assert importlib.util.find_spec("comfyrelay").submodule_search_locations  # the trap: it looks present
    yield importlib.reload(comfyctl.cli)
    monkeypatch.undo()
    importlib.reload(comfyctl.cli)


def test_without_comfyrelay_help_is_unchanged_and_relay_explains_itself(comfyctl_without_comfyrelay):
    cli = comfyctl_without_comfyrelay
    assert "relay" not in runner.invoke(cli.app, ["--help"]).output
    for args in (["relay"], ["relay", "serve", "--port", "9000"], ["relay", "probe", "-o", "json"]):
        r = runner.invoke(cli.app, args)
        assert r.exit_code == 2, args
        assert "comfyctl relay is not available in this build" in r.output
    assert runner.invoke(cli.app, ["fetch", "--help"]).exit_code == 0


def test_a_stray_comfyrelay_directory_does_not_break_comfyctl(comfyctl_beside_a_stray_comfyrelay_dir):
    """It used to: find_spec saw the directory, and importing comfyrelay.cli took fetch down too."""
    cli = comfyctl_beside_a_stray_comfyrelay_dir
    assert runner.invoke(cli.app, ["--version"]).exit_code == 0
    assert runner.invoke(cli.app, ["fetch", "--help"]).exit_code == 0
    r = runner.invoke(cli.app, ["relay", "serve"])
    assert r.exit_code == 2
    assert "comfyctl relay is not available in this build" in r.output


@pytest.fixture
def typer_that_shows_locals(monkeypatch):
    """Typer as it was before 0.23, when pretty_exceptions_show_locals defaulted to True."""
    import importlib

    import comfyctl.cli
    import comfyctl.fetch.cli
    import comfyrelay.cli

    modules = (comfyctl.fetch.cli, comfyrelay.cli, comfyctl.cli)  # comfyctl mounts the other two
    monkeypatch.setitem(typer.Typer.__init__.__kwdefaults__, "pretty_exceptions_show_locals", True)
    yield [importlib.reload(m).app for m in modules]
    monkeypatch.undo()
    for m in modules:
        importlib.reload(m)


def test_no_app_prints_locals_in_a_traceback(typer_that_shows_locals):
    """Locals hold tokens (HF_TOKEN, COMFYUI_MCP_HTTP_TOKEN), so every app turns them off itself."""
    for a in typer_that_shows_locals:
        assert a.pretty_exceptions_show_locals is False, a.info.name


def test_version_is_reportable():
    r = runner.invoke(app, ["--version"])
    assert r.exit_code == 0
    assert r.stdout.strip() == importlib.metadata.version("comfyctl")


def test_no_args_shows_help_rather_than_a_traceback():
    assert "Usage" in runner.invoke(app, []).output
