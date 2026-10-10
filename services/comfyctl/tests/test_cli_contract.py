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
                            "bytes_written", "dry_run", "problems", "ok"}
    assert payload["dry_run"] is True
    assert payload["ok"] is True


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
    src.mkdir(exist_ok=True)
    (src / "_meta.yaml").write_text("name: s\n")
    (src / "a.yaml").write_text(
        "groups:\n  - name: g\n    files:\n"
        "      - {source: 'hf:a/b', file: a.safetensors, install: models/loras/}\n")
    built = tmp_path / "comfy.yaml"
    built.write_text("# stale\n")
    return src, built


def _w(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return str(path)


NOT_YAML = "models: [\n"
UNRESOLVABLE = ("models:\n  - name: g\n    files:\n"
                "      - {source: 'https://example.invalid/a.safetensors', install: models/loras/}\n")


def _build_check_stale(f, t):
    src, built = _stale_build(t)
    return ["build", str(src), "-O", str(built), "--check"]


def _build_no_meta(f, t):
    (t / "no-meta").mkdir()
    return ["build", str(t / "no-meta")]


def _facts(f, t, *extra):
    return ["facts", str(_stale_build(t)[0]), str(f / "lock-good.yaml"), *extra]


def _facts_store_is_models_dir(f, t):
    (t / "root" / "models").mkdir(parents=True)
    return _facts(f, t, "--store", str(t / "root" / "models"))


def _facts_check_stale(f, t):
    src = _stale_build(t)[0]
    _w(src / "a.facts.yaml", "files:\n  models/loras/gone.safetensors: {nsfw: true}\n")
    return ["facts", str(src), "--check"]


def _facts_check_malformed_lineage(f, t):
    _w(t / "src" / "a.yaml", "groups:\n  - name: g\n    files:\n      - {file: a}\n")
    _w(t / "src" / "a.facts.yaml", "files:\n  models/loras/a: {nsfw: true}\n")
    return ["facts", str(t / "src"), "--check"]


# name -> (args builder taking (fixtures, tmp_path), expected exit)
FAILURES = {
    "resolve --from-lock, stale parent": (lambda f, t: [
        "resolve", str(f / "manifest-two-profiles.yaml"), "--profile", "both",
        "--from-lock", str(f / "lock-stale-parent.yaml")], 1),
    "resolve --from-lock, unknown profile": (lambda f, t: [
        "resolve", str(f / "manifest-two-profiles.yaml"), "--profile", "nope",
        "--from-lock", str(f / "lock-stale-parent.yaml")], 2),
    "resolve, unknown profile": (lambda f, t: [
        "resolve", str(f / "manifest-two-profiles.yaml"), "--profile", "nope"], 2),
    "resolve, unresolved source": (lambda f, t: ["resolve", _w(t / "m.yaml", UNRESOLVABLE)], 1),
    "resolve, not YAML": (lambda f, t: ["resolve", _w(t / "m.yaml", NOT_YAML)], 1),
    "resolve, not a mapping": (lambda f, t: ["resolve", _w(t / "m.yaml", "- a\n- b\n")], 1),
    "build, no _meta.yaml": (_build_no_meta, 1),
    "build --check, stale": (_build_check_stale, 1),
    "build --check, missing": (lambda f, t: [
        "build", str(_stale_build(t)[0]), "-O", str(t / "absent.yaml"), "--check"], 1),
    "check, missing file": (lambda f, t: ["check", str(t / "x.yaml"), str(t / "y.yaml")], 2),
    "check, not YAML": (lambda f, t: [
        "check", _w(t / "m.yaml", NOT_YAML), str(f / "lock-good.yaml")], 1),
    "check, schema problem": (lambda f, t: [
        "check", _w(t / "m.yaml", "models:\n  - name: g\n    instal: x\n"),
        str(f / "lock-good.yaml")], 1),
    "check, disagreement": (lambda f, t: [
        "check", str(f / "manifest-for-lock-good.yaml"), str(f / "lock-no-hash.yaml")], 1),
    "fetch, missing lock": (lambda f, t: ["fetch", str(t / "x.yaml"), str(t)], 2),
    "fetch, not YAML": (lambda f, t: ["fetch", _w(t / "l.yaml", NOT_YAML), str(t)], 1),
    "fetch, schema problem": (lambda f, t: [
        "fetch", _w(t / "l.yaml", "models:\n  - {model: a, nonsense: 1}\n"), str(t)], 1),
    "fetch, a refused entry": (lambda f, t: [
        "fetch", str(f / "lock-no-hash.yaml"), str(t / "root"), "--apply"], 1),
    "facts, missing sources": (lambda f, t: [
        "facts", str(t / "nope"), str(f / "lock-good.yaml"), "--store", str(t)], 2),
    "facts, --store is the models dir": (_facts_store_is_models_dir, 2),
    "facts, --headers not JSON": (lambda f, t: _facts(f, t, "--headers", _w(t / "h.json", "{")), 1),
    "facts, --headers a list": (lambda f, t: _facts(f, t, "--headers", _w(t / "h.json", "[]")), 1),
    "facts, --headers value not an object": (lambda f, t: _facts(
        f, t, "--headers", _w(t / "h.json", '{"models/loras/a.safetensors": "x"}')), 1),
    "facts, --headers key not under models/": (lambda f, t: _facts(
        f, t, "--headers", _w(t / "h.json", '{"loras/a.safetensors": {}}')), 1),
    "facts --check, stale sidecar": (_facts_check_stale, 1),
    "facts --check, malformed lineage": (_facts_check_malformed_lineage, 1),
}


@pytest.mark.parametrize("name", list(FAILURES))
def test_every_failure_under_json_writes_a_json_result(name, fixtures, tmp_path):
    """The contract: under -o json, a non-zero exit still puts one JSON object
    on stdout, with `ok: false` and the reason in `problems`, and the reason on
    stderr too. A machine consumer never gets a bare exit code, or a traceback."""
    build_args, code = FAILURES[name]
    r = runner.invoke(app, [*build_args(fixtures, tmp_path), "-o", "json"])
    assert r.exception is None or isinstance(r.exception, SystemExit), repr(r.exception)
    assert r.exit_code == code, r.output
    payload = json.loads(r.stdout)
    assert payload["ok"] is False
    assert payload["problems"] and all(payload["problems"])
    assert r.stderr.strip(), "the reason did not reach stderr"


def test_a_null_header_value_is_an_empty_header(fixtures, tmp_path):
    """`null` is what an extractor writes for a file with no __metadata__. It
    is an empty header, not a malformed one: no traceback, exit 0."""
    args = _facts(fixtures, tmp_path, "--headers",
                  _w(tmp_path / "h.json", '{"models/loras/a.safetensors": null}'))
    r = runner.invoke(app, [*args, "-o", "json"])
    assert r.exception is None or isinstance(r.exception, SystemExit), repr(r.exception)
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout) == {"sidecars": 0}


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
