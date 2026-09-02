"""Resolve and fetch. Network-marked cases hit real hosts on purpose.

Neither the missing-auth bug nor the unencoded-URL bug would have been caught by
a suite that mocks HTTP: both are about what a real host does with a real
request.
"""
import os
import pathlib

import pytest
import yaml
from comfyfetch import fetch, lockfile, resolve

GATED = "f6315581b7cddd450b9aba72b4e9ccf8b6580dc1a6b9538aff43ee26a1a3b6c2"
UPSCALER = "f872d837d3c90ed2e05227bed711af5671a6fd1c9f7d7e91c911a61f155e99da"
UPSCALER_URL = ("https://huggingface.co/ximso/RealESRGAN_x4plus_anime_6B/"
                "resolve/main/RealESRGAN_x4plus_anime_6B.pth")

needs_token = pytest.mark.skipif(
    not os.environ.get("HF_TOKEN"),
    reason="HF_TOKEN unset; a contributor without access should still get a green suite")


def _lock(sha: str | None, path="models/upscale_models/x.pth") -> dict:
    m = {"model": "x.pth", "url": UPSCALER_URL, "paths": [{"path": path}],
         "type": "upscale_model"}
    if sha:
        m["hashes"] = [{"hash": sha, "type": "SHA256"}]
    return {"models": [m]}


def _write(tmp_path, doc, name="l.yaml") -> pathlib.Path:
    p = tmp_path / name
    p.write_text(yaml.safe_dump(doc))
    return p


# --- resolve -----------------------------------------------------------------

@pytest.mark.network
def test_every_bad_source_is_reported_and_no_lock_written(fixtures, capsys):
    rc = resolve.main([str(fixtures / "manifest-broken-sources.yaml")])
    out, err = capsys.readouterr()
    assert rc == 1
    assert out == "", "a partial lock was written"
    for want in ("civitai:2068000", "does-not-exist-xyz", "needs `sha256`"):
        assert want in err, f"{want!r} missing from the report"


@pytest.mark.network
def test_filename_with_spaces_resolves(fixtures, capsys):
    """An unencoded space produces a request that reads as a missing file."""
    assert resolve.main([str(fixtures / "manifest-awkward-filename.yaml")]) == 0
    assert "- model:" in capsys.readouterr().out


@pytest.mark.network
@needs_token
@pytest.mark.parametrize("args", [[], ["--profile", "only"]])
def test_gated_repo_resolves_with_a_token(tmp_path, capsys, args):
    """Regression: auth once loaded only on the no-profile path, so every real
    call went unauthenticated while the no-profile test passed."""
    m = _write(tmp_path, {
        "name": "g", "auth": {"huggingface.co": "${HF_TOKEN}"},
        "models": [{"name": "gated", "files": [{
            "source": "hf:black-forest-labs/FLUX.1-Krea-dev",
            "file": "flux1-krea-dev.safetensors", "install": "models/unet/"}]}],
        "profiles": {"only": ["gated"]}}, "m.yaml")
    assert resolve.main([str(m), *args]) == 0
    assert GATED in capsys.readouterr().out


# --- resolve --from-lock ------------------------------------------------------

def test_from_lock_copies_entries_verbatim(fixtures, capsys):
    rc = resolve.main([str(fixtures / "manifest-two-profiles.yaml"), "--profile", "just-a",
                       "--from-lock", str(fixtures / "lock-two-entries.yaml")])
    assert rc == 0
    derived = yaml.safe_load(capsys.readouterr().out)
    parent = lockfile.load(fixtures / "lock-two-entries.yaml")
    by_path = {lockfile.lock_path(m): m for m in parent["models"]}
    assert len(derived["models"]) == 1
    entry = derived["models"][0]
    assert entry == by_path[lockfile.lock_path(entry)], "not a verbatim copy"


def test_from_lock_refuses_a_stale_parent(fixtures, capsys):
    rc = resolve.main([str(fixtures / "manifest-two-profiles.yaml"), "--profile", "both",
                       "--from-lock", str(fixtures / "lock-stale-parent.yaml")])
    out, err = capsys.readouterr()
    assert rc == 1
    assert out == "", "a partial lock was written"
    assert "stale" in err


def test_from_lock_requires_a_profile(fixtures):
    assert resolve.main([str(fixtures / "manifest-two-profiles.yaml"),
                         "--from-lock", str(fixtures / "lock-two-entries.yaml")]) == 2


# --- fetch -------------------------------------------------------------------

@pytest.mark.network
def test_fetch_verifies_and_is_idempotent(tmp_path):
    lock = _write(tmp_path, _lock(UPSCALER))
    root = tmp_path / "root"
    first = fetch.run(lock, root, dry_run=False)
    assert (first.fetched, first.failed) == (1, 0)
    assert fetch.sha256_file(root / "models/upscale_models/x.pth") == UPSCALER
    second = fetch.run(lock, root, dry_run=False)
    assert (second.present, second.fetched) == (1, 0)


@pytest.mark.network
def test_wrong_hash_is_rejected_and_leaves_nothing(tmp_path):
    lock = _write(tmp_path, _lock("0" * 64))
    root = tmp_path / "root"
    report = fetch.run(lock, root, dry_run=False)
    assert report.failed == 1
    assert any("sha256 mismatch" in line for line in report.lines)
    assert not (root / "models/upscale_models/x.pth").exists()
    assert not list(root.rglob("*.fetch-tmp"))


def test_entry_without_a_hash_is_refused_not_fetched(tmp_path):
    """Fetching it would put unverified bytes in the workspace under the guise
    of a verified run. Offline: it must refuse before any request."""
    report = fetch.run(_write(tmp_path, _lock(None)), tmp_path / "root", dry_run=False)
    assert report.skipped == 1
    assert report.fetched == 0
    assert any("refusing to fetch unverified" in line for line in report.lines)


@pytest.mark.network
def test_mapped_but_unset_credential_does_not_block_a_public_file(tmp_path, monkeypatch):
    """Most HuggingFace files are public; refusing them because HF_TOKEN happens
    to be unset would be wrong."""
    monkeypatch.delenv("HF_TOKEN", raising=False)
    doc = _lock(UPSCALER)
    doc["auth"] = {"huggingface.co": "${HF_TOKEN}"}
    report = fetch.run(_write(tmp_path, doc), tmp_path / "root", dry_run=False)
    assert (report.fetched, report.failed) == (1, 0)


def test_accounting_covers_every_declared_entry(tmp_path):
    """Reading fewer entries than the lock declares must never read as clean."""
    doc = _lock(UPSCALER)
    doc["models"].append({"model": "y", "paths": []})
    report = fetch.run(_write(tmp_path, doc), tmp_path / "root", dry_run=True)
    assert report.would + report.skipped == 2
