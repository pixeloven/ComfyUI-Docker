"""`resolve` and the lock format: the 6.0.0 fixes (#154, #159, #160, #161).

Offline throughout. A direct-URL source with a stated sha256 resolves without
the network, and the hf:/gh: cases stub the two HTTP calls `resolve` makes.
"""
import hashlib
import json
import os
import pathlib
import tempfile

import httpx
import pytest
import yaml
from typer.testing import CliRunner

from comfyctl.fetch import lockfile, resolve, schema
from comfyctl.fetch.cli import app

runner = CliRunner()

SHA_A = "a" * 64
SHA_B = "b" * 64


def write(path: pathlib.Path, doc: dict) -> pathlib.Path:
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return path


def url_file(n: str = "a", sha: str = SHA_A, **extra) -> dict:
    return {"source": f"https://example.invalid/dir/{n}.safetensors",
            "install": "models/checkpoints/", "sha256": sha, **extra}


def manifest(*groups: tuple[str, list[dict]], **top) -> dict:
    return {"models": [{"name": n, "files": f} for n, f in groups], **top}


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("resolve used the network before validating its input")
    monkeypatch.setattr(resolve.http, "head_headers", refuse)
    monkeypatch.setattr(resolve.http, "request", refuse)


# --- #161: a direct URL names its file ------------------------------------------

def test_a_direct_url_without_as_or_file_fails_the_schema():
    problems = schema.validate(manifest(("g", [url_file()])), "comfy")
    assert problems == ["models/0/files/0: a direct-URL source needs `as` "
                        "(or `file`) to name the installed file"]


@pytest.mark.parametrize("extra", [{"as": "x.safetensors"}, {"file": "x.safetensors"}])
def test_a_direct_url_with_as_or_file_passes_the_schema(extra):
    assert schema.validate(manifest(("g", [url_file(**extra)])), "comfy") == []


def test_resolve_refuses_a_direct_url_without_as_or_file(tmp_path, no_network):
    """It used to lock `models/checkpoints/`, and fetch wrote a file over it."""
    m = write(tmp_path / "comfy.yaml", manifest(("g", [url_file()])))
    r = runner.invoke(app, ["resolve", str(m)])
    assert r.exit_code == 2, r.output
    assert r.stdout == "", "a lock was written"
    assert "needs `as` (or `file`)" in r.stderr


def test_check_refuses_a_direct_url_without_as_or_file(tmp_path):
    m = write(tmp_path / "comfy.yaml", manifest(("g", [url_file()])))
    lock = write(tmp_path / "lock.yaml", {"models": [{
        "model": "a.safetensors", "url": "https://example.invalid/dir/a.safetensors",
        "paths": [{"path": "models/checkpoints/"}],
        "hashes": [{"hash": SHA_A, "type": "SHA256"}]}]})
    r = runner.invoke(app, ["check", str(m), str(lock)])
    assert r.exit_code == 1
    assert "needs `as` (or `file`)" in r.stdout
    assert "lock: models/0/paths/0/path" in r.stdout


@pytest.mark.parametrize("extra, name", [
    ({"as": "renamed.safetensors"}, "renamed.safetensors"),
    ({"file": "sub/named.safetensors"}, "named.safetensors"),
])
def test_a_direct_urls_model_and_path_name_the_same_file(tmp_path, extra, name):
    m = write(tmp_path / "comfy.yaml", manifest(("g", [url_file(**extra)])))
    r = runner.invoke(app, ["resolve", str(m)])
    assert r.exit_code == 0, r.output
    (entry,) = yaml.safe_load(r.stdout)["models"]
    assert entry["model"] == name
    assert entry["paths"] == [{"path": f"models/checkpoints/{name}"}]


def test_the_python_api_refuses_a_direct_url_without_a_name():
    with pytest.raises(resolve.Unresolved, match="needs `as` or `file`"):
        resolve._resolve_file(url_file(), resolve.AuthMap.from_document({}))


@pytest.mark.parametrize("path", ["models/checkpoints/", "models/"])
def test_the_lock_schema_refuses_a_directory_path(path):
    lock = {"models": [{"model": "a", "url": "https://example.invalid/a",
                        "paths": [{"path": path}]}]}
    assert any("models/0/paths/0/path" in p for p in schema.validate(lock, "comfy-lock"))


def test_fetch_refuses_a_lock_whose_path_is_a_directory(tmp_path):
    lock = write(tmp_path / "lock.yaml", {"models": [{
        "model": "a.safetensors", "url": "https://example.invalid/a.safetensors",
        "paths": [{"path": "models/checkpoints/"}],
        "hashes": [{"hash": SHA_A, "type": "SHA256"}]}]})
    root = tmp_path / "root"
    r = runner.invoke(app, ["fetch", str(lock), str(root), "--apply"])
    assert r.exit_code == 1
    assert not (root / "models").exists()


# --- #160: one entry per install path --------------------------------------------

def test_a_file_two_groups_share_is_one_entry(tmp_path):
    shared = url_file("vae", **{"as": "vae.safetensors"})
    m = write(tmp_path / "comfy.yaml", manifest(("base", [shared]), ("addon", [dict(shared)])))
    r = runner.invoke(app, ["resolve", str(m)])
    assert r.exit_code == 0, r.output
    assert len(yaml.safe_load(r.stdout)["models"]) == 1
    assert "&id" not in r.stdout and "*id" not in r.stdout


def test_x_metadata_does_not_make_two_declarations_differ(tmp_path):
    one = url_file("vae", **{"as": "vae.safetensors", "x-note": "base"})
    two = url_file("vae", **{"as": "vae.safetensors", "x-note": "addon"})
    m = write(tmp_path / "comfy.yaml", manifest(("base", [one]), ("addon", [two])))
    r = runner.invoke(app, ["resolve", str(m)])
    assert r.exit_code == 0, r.output
    assert len(yaml.safe_load(r.stdout)["models"]) == 1


def test_two_different_files_at_one_path_are_unresolved(tmp_path, no_network):
    m = write(tmp_path / "comfy.yaml", manifest(
        ("base", [url_file("one", SHA_A, **{"as": "vae.safetensors"})]),
        ("addon", [url_file("two", SHA_B, **{"as": "vae.safetensors"})]),
        ("other", [url_file("c", **{"as": "c.safetensors"})])))
    r = runner.invoke(app, ["resolve", str(m), "-o", "json"])
    assert r.exit_code == 1, r.output
    payload = json.loads(r.stdout)
    assert payload["lock_written"] is False
    assert payload["declared"] == 2
    assert payload["resolved"] == 1
    (failure,) = payload["failures"]
    assert failure == ("models/checkpoints/vae.safetensors: declared by 'base' and "
                       "'addon' with a different sha256 and source; one install path "
                       "can hold only one file")


def test_a_shared_file_is_resolved_once_not_once_per_group(tmp_path, monkeypatch):
    """Twice could pin two commits of a moving revision."""
    calls = []

    def head(url, token=None):
        calls.append(url)
        return {"x-repo-commit": f"c{len(calls)}", "x-linked-etag": SHA_A}
    monkeypatch.setattr(resolve.http, "head_headers", head)
    hf = {"source": "hf:o/r", "file": "vae.safetensors", "install": "models/vae/"}
    m = write(tmp_path / "comfy.yaml", manifest(("base", [hf]), ("addon", [dict(hf)])))
    r = runner.invoke(app, ["resolve", str(m)])
    assert r.exit_code == 0, r.output
    assert len(calls) == 1
    assert len(yaml.safe_load(r.stdout)["models"]) == 1


def _hf_parent(tmp_path, *paths: str) -> pathlib.Path:
    return write(tmp_path / "parent.yaml", {"models": [{
        "model": p.rsplit("/", 1)[1], "url": f"https://huggingface.co/o/r/resolve/abc/{p}",
        "paths": [{"path": p}], "hashes": [{"hash": SHA_A, "type": "SHA256"}]}
        for p in paths]})


def test_from_lock_selects_a_shared_file_once(tmp_path):
    hf = {"source": "hf:o/r", "file": "vae.safetensors", "install": "models/vae/"}
    m = write(tmp_path / "comfy.yaml", manifest(
        ("base", [hf]), ("addon", [dict(hf)]), profiles={"all": ["base", "addon"]}))
    parent = _hf_parent(tmp_path, "models/vae/vae.safetensors")
    r = runner.invoke(app, ["resolve", str(m), "--profile", "all", "--from-lock", str(parent)])
    assert r.exit_code == 0, r.output
    assert len(yaml.safe_load(r.stdout)["models"]) == 1
    assert "*id" not in r.stdout


def test_from_lock_refuses_a_conflicting_selection(tmp_path):
    m = write(tmp_path / "comfy.yaml", manifest(
        ("base", [{"source": "hf:o/r", "file": "vae.safetensors", "install": "models/vae/"}]),
        ("addon", [{"source": "hf:o/other", "file": "vae.safetensors", "install": "models/vae/"}]),
        profiles={"all": ["base", "addon"]}))
    parent = _hf_parent(tmp_path, "models/vae/vae.safetensors")
    r = runner.invoke(app, ["resolve", str(m), "--profile", "all", "--from-lock", str(parent)])
    assert r.exit_code == 1
    assert r.stdout == ""
    assert "with a different source" in " ".join(r.stderr.split())


def test_from_lock_refuses_a_parent_listing_a_path_twice(tmp_path):
    hf = {"source": "hf:o/r", "file": "vae.safetensors", "install": "models/vae/"}
    m = write(tmp_path / "comfy.yaml", manifest(("base", [hf]), profiles={"p": ["base"]}))
    parent = _hf_parent(tmp_path, "models/vae/vae.safetensors", "models/vae/vae.safetensors")
    r = runner.invoke(app, ["resolve", str(m), "--profile", "p", "--from-lock", str(parent)])
    assert r.exit_code == 1
    assert r.stdout == ""
    assert "more than once" in r.stderr


def test_from_lock_with_an_unknown_profile_is_a_request_error(tmp_path):
    """Exit 2, as the same --profile is without --from-lock."""
    hf = {"source": "hf:o/r", "file": "vae.safetensors", "install": "models/vae/"}
    m = write(tmp_path / "comfy.yaml", manifest(("base", [hf]), profiles={"p": ["base"]}))
    parent = _hf_parent(tmp_path, "models/vae/vae.safetensors")
    r = runner.invoke(app, ["resolve", str(m), "--profile", "nope", "--from-lock", str(parent)])
    assert r.exit_code == 2, r.output
    assert "no such profile: nope" in r.stderr


def test_check_reports_a_duplicate_lock_path(tmp_path):
    hf = {"source": "hf:o/r", "file": "vae.safetensors", "install": "models/vae/"}
    m = write(tmp_path / "comfy.yaml", manifest(("base", [hf])))
    lock = _hf_parent(tmp_path, "models/vae/vae.safetensors", "models/vae/vae.safetensors")
    r = runner.invoke(app, ["check", str(m), str(lock), "-o", "json"])
    assert r.exit_code == 1
    assert "DUPLICATE    models/vae/vae.safetensors" in json.loads(r.stdout)["problems"]


def test_check_reports_a_manifest_conflict_offline(tmp_path):
    m = write(tmp_path / "comfy.yaml", manifest(
        ("base", [{"source": "hf:o/r", "file": "vae.safetensors", "install": "models/vae/"}]),
        ("addon", [{"source": "hf:o/other", "file": "vae.safetensors", "install": "models/vae/"}])))
    lock = _hf_parent(tmp_path, "models/vae/vae.safetensors")
    r = runner.invoke(app, ["check", str(m), str(lock), "-o", "json"])
    assert r.exit_code == 1
    assert ("CONFLICT     models/vae/vae.safetensors: declared by 'base' and 'addon' "
            "with a different source; one install path can hold only one file"
            in json.loads(r.stdout)["problems"])


def test_dump_never_writes_an_alias():
    entry = {"model": "a", "url": "u", "paths": [{"path": "models/a/a"}]}
    assert "&" not in lockfile.dump(None, [entry, entry])


# --- #154: validate before resolving ---------------------------------------------

def test_a_typo_is_a_schema_problem_not_a_traceback(tmp_path, no_network):
    m = write(tmp_path / "comfy.yaml", manifest(("a", [{
        "source": "hf:o/r", "file": "a.safetensors", "instal": "models/checkpoints/"}])))
    r = runner.invoke(app, ["resolve", str(m)])
    assert r.exit_code == 2, r.output
    assert not isinstance(r.exception, KeyError)
    assert "'install' is a required property" in r.stderr
    assert r.stdout == ""


def test_json_mode_carries_the_schema_problems(tmp_path, no_network):
    m = write(tmp_path / "comfy.yaml", manifest(("a", [{
        "source": "hf:o/r", "file": "a.safetensors", "instal": "models/checkpoints/"}])))
    r = runner.invoke(app, ["resolve", str(m), "-o", "json"])
    assert r.exit_code == 2
    payload = json.loads(r.stdout)
    assert payload["ok"] is False and payload["lock_written"] is False
    assert any("'install' is a required property" in p for p in payload["problems"])


def test_the_semantic_checks_run_too(tmp_path, no_network):
    """`check` refuses a capability no profile can satisfy; so does resolve."""
    m = write(tmp_path / "comfy.yaml", manifest(
        ("a", [url_file(**{"as": "a.safetensors"})]),
        profiles={"p": ["a"]},
        capabilities={"render": {"profiles": ["p"], "requires": ["vae"]}}))
    r = runner.invoke(app, ["resolve", str(m)])
    assert r.exit_code == 2, r.output
    assert "requires type 'vae'" in r.stderr


def test_a_malformed_parent_is_reported_as_the_parents_problem(tmp_path, no_network):
    m = write(tmp_path / "comfy.yaml", manifest(
        ("a", [{"source": "hf:o/r", "file": "a.safetensors", "install": "models/checkpoints/"}]),
        profiles={"p": ["a"]}))
    parent = write(tmp_path / "parent.yaml", {"models": [{
        "model": "a.safetensors", "url": "https://example.invalid/a.safetensors",
        "paths": [{}]}]})
    r = runner.invoke(app, ["resolve", str(m), "--profile", "p", "--from-lock", str(parent),
                            "-o", "json"])
    assert r.exit_code == 2, r.output
    assert "parent: models/0/paths/0: 'path' is a required property" in \
        json.loads(r.stdout)["problems"]


# --- no usable temp directory -----------------------------------------------------

class _Body:
    def __init__(self, data: bytes):
        self._data = data

    def read(self, n: int = -1) -> bytes:
        out, self._data = self._data[:n], self._data[n:]
        return out

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


def test_download_and_hash_needs_no_temp_directory(tmp_path, monkeypatch):
    """A read-only root has no usable TMPDIR. Hashing needs none, and once
    crashed the whole pass with a traceback for wanting one."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "does-not-exist"))
    body = b"not an LFS file"
    monkeypatch.setattr(resolve.http, "head_headers", lambda url, token=None: {
        "x-repo-commit": "abc", "x-linked-etag": "1" * 40})
    monkeypatch.setattr(resolve.http, "request", lambda url, **k: _Body(body))
    m = write(tmp_path / "comfy.yaml", manifest(("a", [{
        "source": "hf:o/r", "file": "config.json", "install": "models/configs/"}])))
    r = runner.invoke(app, ["resolve", str(m)])
    assert r.exit_code == 0, r.output
    (entry,) = yaml.safe_load(r.stdout)["models"]
    assert entry["hashes"] == [{"hash": hashlib.sha256(body).hexdigest(), "type": "SHA256"}]


def test_a_failed_download_is_that_entrys_failure_not_the_runs(tmp_path, monkeypatch):
    def broken(url, **k):
        raise httpx.ConnectError("connection refused")
    monkeypatch.setattr(resolve.http, "head_headers", lambda url, token=None: {
        "x-repo-commit": "abc", "x-linked-etag": "1" * 40})
    monkeypatch.setattr(resolve.http, "request", broken)
    m = write(tmp_path / "comfy.yaml", manifest(
        ("a", [{"source": "hf:o/r", "file": "config.json", "install": "models/configs/"}]),
        ("b", [url_file(**{"as": "b.safetensors"})])))
    r = runner.invoke(app, ["resolve", str(m), "-o", "json"])
    assert r.exit_code == 1, r.output
    payload = json.loads(r.stdout)
    assert payload["resolved"] == 1
    (failure,) = payload["failures"]
    assert "download to hash it failed" in failure


# --- #159: -O/--out and --header ---------------------------------------------------

def test_out_writes_the_lock_and_header_prepends(tmp_path):
    m = write(tmp_path / "comfy.yaml", manifest(("a", [url_file(**{"as": "a.safetensors"})])))
    header = tmp_path / "header.txt"
    header.write_text("# GENERATED -- do not edit\n")
    lock = tmp_path / "lock.yaml"
    r = runner.invoke(app, ["resolve", str(m), "-O", str(lock), "--header", str(header)])
    assert r.exit_code == 0, r.output
    assert r.stdout == ""
    text = lock.read_text()
    assert text.startswith("# GENERATED -- do not edit\nmodels:\n")
    assert schema.validate(yaml.safe_load(text), "comfy-lock") == []
    assert [p.name for p in tmp_path.iterdir() if "resolve-tmp" in p.name] == []


@pytest.mark.parametrize("entry, code, why", [
    ({"source": "https://example.invalid/a.safetensors", "as": "a.safetensors",
      "install": "models/checkpoints/"}, 1, "needs `sha256`"),   # unresolved
    (url_file(), 2, "1 schema problem(s)"),                       # refused before resolving
])
def test_a_failed_resolve_leaves_the_existing_lock_untouched(tmp_path, entry, code, why):
    m = write(tmp_path / "comfy.yaml", manifest(("a", [entry])))
    lock = tmp_path / "lock.yaml"
    lock.write_text("# the committed, good lock\n")
    r = runner.invoke(app, ["resolve", str(m), "-O", str(lock)])
    assert r.exit_code == code, r.output
    assert why in r.stderr
    assert lock.read_text() == "# the committed, good lock\n"
    assert [p.name for p in tmp_path.iterdir() if "resolve-tmp" in p.name] == []


def test_out_works_with_from_lock_and_json(tmp_path):
    hf = {"source": "hf:o/r", "file": "vae.safetensors", "install": "models/vae/"}
    m = write(tmp_path / "comfy.yaml", manifest(("base", [hf]), profiles={"p": ["base"]}))
    parent = _hf_parent(tmp_path, "models/vae/vae.safetensors")
    lock = tmp_path / "p.yaml"
    r = runner.invoke(app, ["resolve", str(m), "--profile", "p", "--from-lock", str(parent),
                            "-O", str(lock), "-o", "json"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["path"] == str(lock)
    assert yaml.safe_load(lock.read_text())["models"] == yaml.safe_load(parent.read_text())["models"]


@pytest.mark.parametrize("args, why", [
    (["--header", "missing-header.txt"], "no such header file"),
    (["-O", "no-such-dir/lock.yaml"], "no such directory for --out"),
])
def test_a_missing_header_or_out_directory_is_a_request_error(tmp_path, args, why):
    m = write(tmp_path / "comfy.yaml", manifest(("a", [url_file(**{"as": "a.safetensors"})])))
    args = [str(tmp_path / a) if not a.startswith("-") else a for a in args]
    r = runner.invoke(app, ["resolve", str(m), *args])
    assert r.exit_code == 2, r.output
    assert why in r.stderr


# --- review round: names, containment, conflicts, -O, network errors -------------

@pytest.mark.parametrize("bad", [
    {"as": "sub/"}, {"as": ""}, {"as": ".."}, {"as": "."}, {"as": "sub/../x"},
    {"as": "..\\..\\evil"}, {"file": "sub\\..\\x"}, {"install": "models/a\\..\\"},
    {"file": ""}, {"file": "sub/.."}, {"file": "../x.safetensors"}, {"file": "/x.safetensors"},
    {"install": "models/../"}, {"install": "models/../../etc/"}, {"install": "models/./vae/"},
    {"install": "models//"},
])
def test_names_and_directories_cannot_be_empty_or_climb_out(bad):
    entry = url_file(**{"as": "a.safetensors"}) | bad
    assert schema.validate(manifest(("g", [entry])), "comfy") != [], bad


@pytest.mark.parametrize("path", [
    "models/../x.safetensors", "models/vae/../../x", "models/./x", "models//x", "models/vae/..",
    "models/..\\..\\evil", "models/vae/a\\b",
])
def test_the_lock_schema_refuses_a_path_that_climbs_out(path):
    lock = {"models": [{"model": "x", "url": "https://example.invalid/x",
                        "paths": [{"path": path}]}]}
    assert any("models/0/paths/0/path" in p for p in schema.validate(lock, "comfy-lock"))


def test_an_as_with_a_trailing_slash_is_refused_before_anything_is_written(tmp_path, no_network):
    """It once resolved, exit 0, to a directory path that `check` then refused."""
    m = write(tmp_path / "comfy.yaml", manifest(("g", [url_file(**{"as": "sub/"})])))
    lock = tmp_path / "lock.yaml"
    r = runner.invoke(app, ["resolve", str(m), "-O", str(lock)])
    assert r.exit_code == 2, r.output
    assert "models/0/files/0/as: 'sub/' does not match" in " ".join(r.stderr.split())
    assert not lock.exists()


def test_fetch_refuses_a_path_outside_the_root_even_without_the_schema(tmp_path, monkeypatch):
    from comfyctl.fetch import fetch as fetch_mod

    def refuse(*a, **k):
        raise AssertionError("fetched a path outside the root")
    monkeypatch.setattr(fetch_mod.http, "request", refuse)
    lock = write(tmp_path / "lock.yaml", {"models": [{
        "model": "x", "url": "https://example.invalid/x",
        "paths": [{"path": "models/../../escaped.safetensors"}],
        "hashes": [{"hash": SHA_A, "type": "SHA256"}]}]})
    root = tmp_path / "a" / "root"
    root.mkdir(parents=True)
    report = fetch_mod.run(lock, root, dry_run=False)
    assert report.failed == 1
    assert "leaves the root" in report.lines[0]
    assert not (tmp_path / "escaped.safetensors").exists()


def test_the_schema_is_plain_json_schema():
    """No ajv-errors keyword: Ajv's strict mode refuses unknown keywords."""
    for name in ("comfy", "comfy-lock"):
        assert "errorMessage" not in json.dumps(schema.load(name))


@pytest.mark.parametrize("one, two", [
    ({"revision": "main"}, {}),
    ({"as": "vae.safetensors"}, {}),
    ({"sha256": SHA_A.upper()}, {"sha256": SHA_A}),
])
def test_two_spellings_of_one_file_do_not_conflict(one, two):
    base = {"source": "hf:o/r", "file": "sub/vae.safetensors", "install": "models/vae/"}
    groups = [{"name": "a", "files": [base | one]}, {"name": "b", "files": [base | two]}]
    assert lockfile.conflicts(groups) == {}


def test_a_conflict_names_only_the_groups_and_keys_that_differ():
    base = {"source": "hf:o/r", "file": "vae.safetensors", "install": "models/vae/", "type": "vae"}
    groups = [{"name": "a", "files": [base]}, {"name": "b", "files": [dict(base)]},
              {"name": "c", "files": [base | {"source": "hf:o/other"}]}]
    assert lockfile.conflicts(groups) == {
        "models/vae/vae.safetensors": "models/vae/vae.safetensors: declared by 'a' and "
        "'c' with a different source; one install path can hold only one file"}


def test_an_error_mid_stream_fails_that_entry_only(tmp_path, monkeypatch):
    class Broken(_Body):
        def read(self, n=-1):
            if self._data:
                return super().read(n)
            raise httpx.ReadError("connection reset")
    monkeypatch.setattr(resolve.http, "head_headers", lambda url, token=None: {
        "x-repo-commit": "abc", "x-linked-etag": "1" * 40})
    monkeypatch.setattr(resolve.http, "request", lambda url, **k: Broken(b"partial"))
    m = write(tmp_path / "comfy.yaml", manifest(
        ("a", [{"source": "hf:o/r", "file": "config.json", "install": "models/configs/"}]),
        ("b", [url_file(**{"as": "b.safetensors"})])))
    r = runner.invoke(app, ["resolve", str(m), "-o", "json"])
    assert r.exit_code == 1, r.output
    payload = json.loads(r.stdout)
    assert payload["resolved"] == 1
    (failure,) = payload["failures"]
    assert "download to hash it failed: connection reset" in failure


@pytest.mark.parametrize("where", ["hf", "gh", "civitai"])
def test_a_network_error_in_any_source_fails_that_entry_only(tmp_path, monkeypatch, where):
    def down(*a, **k):
        raise httpx.ConnectTimeout("timed out")
    monkeypatch.setattr(resolve.http, "head_headers", down)
    monkeypatch.setattr(resolve.http, "request", down)
    entry = {
        "hf": {"source": "hf:o/r", "file": "a.safetensors", "install": "models/a/"},
        "gh": {"source": "gh:o/r@v1", "file": "a.pth", "install": "models/a/"},
        "civitai": {"source": "civitai:1", "as": "a.safetensors", "install": "models/a/"},
    }[where]
    m = write(tmp_path / "comfy.yaml", manifest(
        ("a", [entry]), ("b", [url_file(**{"as": "b.safetensors"})])))
    r = runner.invoke(app, ["resolve", str(m), "-o", "json"])
    assert r.exit_code == 1, r.output
    payload = json.loads(r.stdout)
    assert payload["resolved"] == 1
    (failure,) = payload["failures"]
    assert failure.startswith(entry["source"]) and "ConnectTimeout" in failure


def _ok_manifest(tmp_path) -> pathlib.Path:
    return write(tmp_path / "comfy.yaml", manifest(("a", [url_file(**{"as": "a.safetensors"})])))


def test_out_naming_a_directory_is_a_request_error(tmp_path, no_network):
    (tmp_path / "locks").mkdir()
    r = runner.invoke(app, ["resolve", str(_ok_manifest(tmp_path)), "-O", str(tmp_path / "locks")])
    assert r.exit_code == 2
    assert "is a directory" in r.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes anywhere")
def test_out_in_an_unwritable_directory_is_a_request_error(tmp_path, no_network):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o555)
    try:
        r = runner.invoke(app, ["resolve", str(_ok_manifest(tmp_path)), "-O", str(ro / "l.yaml")])
    finally:
        ro.chmod(0o755)
    assert r.exit_code == 2
    assert "not writable" in r.stderr


def test_out_refuses_to_overwrite_an_input(tmp_path):
    hf = {"source": "hf:o/r", "file": "vae.safetensors", "install": "models/vae/"}
    m = write(tmp_path / "comfy.yaml", manifest(("base", [hf]), profiles={"p": ["base"]}))
    parent = _hf_parent(tmp_path, "models/vae/vae.safetensors")
    before = parent.read_text()
    r = runner.invoke(app, ["resolve", str(m), "--profile", "p", "--from-lock", str(parent),
                            "-O", str(parent)])
    assert r.exit_code == 2
    assert "would overwrite an input" in r.stderr
    assert parent.read_text() == before
    r = runner.invoke(app, ["resolve", str(m), "-O", str(m)])
    assert r.exit_code == 2


def test_out_writes_through_a_symlink_and_keeps_the_mode(tmp_path):
    real = tmp_path / "real.yaml"
    real.write_text("# old\n")
    real.chmod(0o640)
    link = tmp_path / "link.yaml"
    link.symlink_to(real)
    r = runner.invoke(app, ["resolve", str(_ok_manifest(tmp_path)), "-O", str(link)])
    assert r.exit_code == 0, r.output
    assert link.is_symlink()
    assert real.read_text().startswith("models:")
    assert real.stat().st_mode & 0o777 == 0o640


# --- re-review: Windows separators, `as:` subdirectories, symlinks, bad bodies ----

def test_as_may_name_a_subdirectory(tmp_path):
    """Owner decision: `as: sub/x.safetensors` installs into `install`/sub/."""
    m = write(tmp_path / "comfy.yaml", manifest(("g", [url_file(**{"as": "sub/x.safetensors"})])))
    r = runner.invoke(app, ["resolve", str(m)])
    assert r.exit_code == 0, r.output
    (entry,) = yaml.safe_load(r.stdout)["models"]
    assert entry["paths"] == [{"path": "models/checkpoints/sub/x.safetensors"}]


@pytest.mark.parametrize("rel", ["models/..\\..\\evil", "models\\x", "models/vae/a\\b"])
def test_fetch_refuses_a_backslash_even_without_the_schema(tmp_path, monkeypatch, rel):
    """On Windows `models/..\\..\\evil` climbs out of the root."""
    from comfyctl.fetch import fetch as fetch_mod

    def refuse(*a, **k):
        raise AssertionError("fetched a path with a backslash")
    monkeypatch.setattr(fetch_mod.http, "request", refuse)
    lock = write(tmp_path / "lock.yaml", {"models": [{
        "model": "x", "url": "https://example.invalid/x", "paths": [{"path": rel}],
        "hashes": [{"hash": SHA_A, "type": "SHA256"}]}]})
    report = fetch_mod.run(lock, tmp_path / "root", dry_run=False)
    assert report.failed == 1
    assert "leaves the root" in report.lines[0]


def test_an_extra_copy_replaces_a_symlink_rather_than_writing_through_it(tmp_path, monkeypatch):
    from comfyctl.fetch import fetch as fetch_mod

    body = b"model bytes"
    monkeypatch.setattr(fetch_mod.http, "request", lambda url, **k: _Body(body))
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"precious")
    root = tmp_path / "root"
    (root / "models" / "b").mkdir(parents=True)
    (root / "models" / "b" / "x.bin").symlink_to(outside)
    lock = write(tmp_path / "lock.yaml", {"models": [{
        "model": "x.bin", "url": "https://example.invalid/x.bin",
        "paths": [{"path": "models/a/x.bin"}, {"path": "models/b/x.bin"}],
        "hashes": [{"hash": hashlib.sha256(body).hexdigest(), "type": "SHA256"}]}]})
    report = fetch_mod.run(lock, root, dry_run=False)
    assert report.fetched == 1, report.lines
    assert outside.read_bytes() == b"precious"
    copy = root / "models" / "b" / "x.bin"
    assert not copy.is_symlink() and copy.read_bytes() == body


@pytest.mark.parametrize("body", [b"<html>a proxy's error page</html>", b'{"files": [{}]}'])
def test_a_bad_api_body_fails_that_entry_only(tmp_path, monkeypatch, body):
    """HTML where JSON was expected (ValueError), or JSON missing a key (KeyError)."""
    monkeypatch.setattr(resolve.http, "request", lambda url, **k: _Body(body))
    m = write(tmp_path / "comfy.yaml", manifest(
        ("a", [{"source": "civitai:1", "as": "a.safetensors", "install": "models/a/"}]),
        ("b", [url_file(**{"as": "b.safetensors"})])))
    r = runner.invoke(app, ["resolve", str(m), "-o", "json"])
    assert r.exit_code == 1, r.output
    payload = json.loads(r.stdout)
    assert payload["resolved"] == 1
    (failure,) = payload["failures"]
    assert failure.startswith("civitai:1: ")


def test_a_direct_url_named_by_as_or_by_file_is_one_file(tmp_path):
    a = url_file("x", **{"as": "x.safetensors"})
    b = url_file("x", **{"file": "x.safetensors"})
    m = write(tmp_path / "comfy.yaml", manifest(("base", [a]), ("addon", [b])))
    r = runner.invoke(app, ["resolve", str(m)])
    assert r.exit_code == 0, r.output
    assert len(yaml.safe_load(r.stdout)["models"]) == 1
