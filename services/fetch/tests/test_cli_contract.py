"""The CLI's contract: exit codes and machine-readable output.

Automation and agents read these. A change here is a breaking change even when
every other test passes, so they are asserted rather than assumed.
"""
import json

import pytest
from comfyfetch.cli import app
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
    assert r.stdout.strip() == importlib.metadata.version("comfyfetch")


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
