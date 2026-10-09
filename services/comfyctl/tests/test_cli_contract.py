"""The CLI's contract: exit codes and machine-readable output.

Automation and agents read these. A change here is a breaking change even when
every other test passes, so they are asserted rather than assumed.
"""
import json

import pytest
from comfyctl.fetch.cli import app
from typer.testing import CliRunner

runner = CliRunner()


def test_no_args_shows_help_rather_than_a_traceback():
    r = runner.invoke(app, [])
    assert "Usage" in r.output


@pytest.mark.parametrize("verb", ["resolve", "fetch", "check"])
def test_every_verb_is_reachable(verb):
    assert runner.invoke(app, [verb, "--help"]).exit_code == 0


def test_missing_file_is_a_request_error_not_a_failure(tmp_path):
    """2 means 'the request was wrong', distinct from 1 'it really failed'."""
    r = runner.invoke(app, ["check", str(tmp_path / "nope.yaml"), str(tmp_path / "no.yaml")])
    assert r.exit_code == 2


def test_from_lock_without_profile_is_a_request_error(fixtures):
    r = runner.invoke(app, ["resolve", str(fixtures / "manifest-two-profiles.yaml"),
                            "--from-lock", str(fixtures / "lock-two-entries.yaml")])
    assert r.exit_code == 2


def test_disagreement_is_a_failure_not_a_request_error(fixtures):
    r = runner.invoke(app, ["check", str(fixtures / "manifest-for-lock-good.yaml"),
                            str(fixtures / "lock-no-hash.yaml")])
    assert r.exit_code == 1


def test_check_json_has_stable_keys(fixtures):
    r = runner.invoke(app, ["check", str(fixtures / "manifest-for-lock-good.yaml"),
                            str(fixtures / "lock-good.yaml"), "-o", "json"])
    assert r.exit_code == 0
    payload = json.loads(r.stdout)
    assert set(payload) == {"declared", "locked", "problems", "ok"}
    assert payload["ok"] is True


def test_fetch_json_has_stable_keys(fixtures, tmp_path):
    r = runner.invoke(app, ["fetch", str(fixtures / "lock-good.yaml"), str(tmp_path),
                            "-o", "json"])
    payload = json.loads(r.stdout)
    assert set(payload) == {"present", "fetched", "skipped", "failed", "would_fetch",
                            "bytes_written", "dry_run", "problems"}
    assert payload["dry_run"] is True


def test_json_mode_keeps_stdout_parseable(fixtures, tmp_path):
    """Progress must not leak into stdout, or an agent cannot parse the result."""
    r = runner.invoke(app, ["fetch", str(fixtures / "lock-good.yaml"), str(tmp_path),
                            "-o", "json"])
    json.loads(r.stdout)  # raises if anything else was written there


def test_result_goes_to_stdout_not_stderr(fixtures, tmp_path):
    """Progress belongs on stderr; the RESULT belongs on stdout.

    Regression: both went to stderr, so `comfyfetch fetch ... | grep present`
    saw an empty stream and matched nothing -- a pipeline that looks like it
    passes because there is nothing to fail against.
    """
    runner_split = CliRunner()
    r = runner_split.invoke(app, ["fetch", str(fixtures / "lock-good.yaml"),
                                  str(tmp_path)])
    assert r.exit_code == 0
    assert "present:" in r.stdout, "the summary is not on stdout"


def test_resolve_puts_only_the_lock_on_stdout(fixtures):
    """`resolve > lock.yaml` must capture the lock and none of the chatter."""
    r = runner.invoke(app, ["resolve", str(fixtures / "manifest-two-profiles.yaml"),
                            "--profile", "just-a",
                            "--from-lock", str(fixtures / "lock-two-entries.yaml")])
    assert r.exit_code == 0
    import yaml
    assert yaml.safe_load(r.stdout)["models"], "stdout is not a parseable lock"


def test_version_is_reportable():
    """A consumer in the wild has no other way to know what they have."""
    import importlib.metadata
    r = runner.invoke(app, ["--version"])
    assert r.exit_code == 0
    assert r.stdout.strip() == importlib.metadata.version("comfyctl")


def test_progress_goes_to_stderr_not_stdout(fixtures, tmp_path):
    """A long fetch must say what it is doing, without polluting the result.

    The first real in-cluster run printed nothing for several minutes, which is
    indistinguishable from a hung job — but progress on stdout would break
    `fetch | grep` and the json contract.
    """
    r = CliRunner().invoke(app, ["fetch", str(fixtures / "lock-good.yaml"),
                                 str(tmp_path)])
    assert "present:" in r.stdout


def test_json_mode_emits_no_progress(fixtures, tmp_path):
    import json
    r = runner.invoke(app, ["fetch", str(fixtures / "lock-good.yaml"),
                            str(tmp_path), "-o", "json"])
    json.loads(r.stdout)


@pytest.mark.parametrize("verb", ["build", "resolve", "fetch", "check", "facts"])
def test_module_entry_point_sees_every_verb(verb):
    """`python -m comfyctl.fetch.cli <verb>` must reach every verb.

    Regression: the `__main__` guard sat above `build` and `facts`, so it ran
    the app before they were registered and answered "No such command 'build'".
    """
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-m", "comfyctl.fetch.cli", verb, "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ---- a failure under -o json still says why (#152) --------------------------
#
# These paths reported through Out.problem(), a no-op under json, and exited
# without a result: exit 1 and zero bytes on BOTH streams.

def _stale_build(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "_meta.yaml").write_text("name: s\n")
    (src / "a.yaml").write_text(
        "groups:\n  - name: g\n    files:\n"
        "      - {source: 'hf:a/b', file: a.safetensors, install: models/loras/}\n")
    built = tmp_path / "comfy.yaml"
    built.write_text("# stale\n")
    return src, built


def _failing(name, fixtures, tmp_path):
    """(args, expected exit) for each failure path, built lazily per test."""
    src, built = _stale_build(tmp_path)
    (tmp_path / "no-meta").mkdir()
    manifest, parent = fixtures / "manifest-two-profiles.yaml", fixtures / "lock-stale-parent.yaml"
    return {
        "resolve --from-lock, stale parent": (
            ["resolve", str(manifest), "--profile", "both", "--from-lock", str(parent)], 1),
        "resolve --from-lock, unknown profile": (
            ["resolve", str(manifest), "--profile", "nope", "--from-lock", str(parent)], 2),
        "resolve, unknown profile": (
            ["resolve", str(manifest), "--profile", "nope"], 2),
        "build, no _meta.yaml": (["build", str(tmp_path / "no-meta")], 1),
        "build --check, stale": (["build", str(src), "-O", str(built), "--check"], 1),
        "build --check, missing": (
            ["build", str(src), "-O", str(tmp_path / "absent.yaml"), "--check"], 1),
        "check, missing file": (["check", str(tmp_path / "x.yaml"), str(tmp_path / "y.yaml")], 2),
        "fetch, missing lock": (["fetch", str(tmp_path / "x.yaml"), str(tmp_path)], 2),
        "facts, missing sources": (["facts", str(tmp_path / "nope"), str(parent),
                                    "--store", str(tmp_path)], 2),
    }[name]


FAILURES = ["resolve --from-lock, stale parent", "resolve --from-lock, unknown profile",
            "resolve, unknown profile", "build, no _meta.yaml", "build --check, stale",
            "build --check, missing", "check, missing file", "fetch, missing lock",
            "facts, missing sources"]


@pytest.mark.parametrize("name", FAILURES)
def test_every_failure_under_json_writes_a_json_result(name, fixtures, tmp_path):
    """The contract: under -o json, a non-zero exit still puts one JSON object
    on stdout, with `ok: false` and the reason in `problems`, and the reason on
    stderr too. A machine consumer never gets a bare exit code."""
    args, code = _failing(name, fixtures, tmp_path)
    r = runner.invoke(app, [*args, "-o", "json"])
    assert r.exit_code == code, r.output
    payload = json.loads(r.stdout)
    assert payload["ok"] is False
    assert payload["problems"] and all(payload["problems"])
    assert r.stderr.strip(), "the reason did not reach stderr"


def test_from_lock_failure_names_the_profile_and_the_stale_paths(fixtures):
    r = runner.invoke(app, ["resolve", str(fixtures / "manifest-two-profiles.yaml"),
                            "--profile", "both",
                            "--from-lock", str(fixtures / "lock-stale-parent.yaml"),
                            "-o", "json"])
    assert r.exit_code == 1
    payload = json.loads(r.stdout)
    assert (payload["profile"], payload["entries"]) == ("both", 0)
    assert "models/vae_approx/taesdxl_decoder.safetensors" in payload["problems"][0]


def test_build_check_failure_says_stale(tmp_path):
    src, built = _stale_build(tmp_path)
    r = runner.invoke(app, ["build", str(src), "-O", str(built), "--check", "-o", "json"])
    assert r.exit_code == 1
    assert json.loads(r.stdout)["stale"] is True


def test_an_unknown_profile_with_from_lock_is_a_request_error(fixtures):
    """Exit 2, as it is without --from-lock: the request named a profile the
    manifest does not have. It was 1 on the --from-lock path."""
    r = runner.invoke(app, ["resolve", str(fixtures / "manifest-two-profiles.yaml"),
                            "--profile", "nope",
                            "--from-lock", str(fixtures / "lock-two-entries.yaml")])
    assert r.exit_code == 2, r.output
    assert "no such profile" in r.output
