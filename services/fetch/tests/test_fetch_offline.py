"""The verification core of `fetch`, offline.

The existing fetch tests are almost all `@pytest.mark.network`, so in CI --
where the network marker is deselected -- the code that decides whether bytes
are trustworthy ran in exactly one test. Mutation-probing it confirmed the gap:
deleting the present-file short-circuit, the `.fetch-tmp` cleanup on mismatch
and the extra-paths copy each left the suite green.

respx replaces the host, not the logic: every assertion below is about what
fetch does with the bytes, which is the part that must not be trusted to a
skipped marker.
"""
from __future__ import annotations

import hashlib
import pathlib

import httpx
import pytest
import respx
import yaml
from comfyfetch import fetch

URL = "https://example.invalid/m.safetensors"
BODY = b"weights, allegedly" * 1000
SHA = hashlib.sha256(BODY).hexdigest()
REL = "models/loras/m.safetensors"


def lock(tmp_path: pathlib.Path, *, sha: str | None = SHA,
         paths: list[str] | None = None, url: str | None = URL) -> pathlib.Path:
    entry: dict = {"model": "m.safetensors",
                   "paths": [{"path": p} for p in (paths or [REL])]}
    if url:
        entry["url"] = url
    if sha:
        entry["hashes"] = [{"hash": sha, "type": "SHA256"}]
    p = tmp_path / "lock.yaml"
    p.write_text(yaml.safe_dump({"models": [entry]}))
    return p


@pytest.fixture
def served():
    """The file, served once per request, with a request counter."""
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(URL).mock(return_value=httpx.Response(200, content=BODY))
        yield route


def test_a_verified_fetch_lands_the_bytes_and_no_temp_file(tmp_path, served):
    report = fetch.run(lock(tmp_path), tmp_path / "root", dry_run=False)
    assert (report.fetched, report.failed, report.skipped) == (1, 0, 0)
    assert (tmp_path / "root" / REL).read_bytes() == BODY
    assert not list((tmp_path / "root").rglob("*.fetch-tmp"))


def test_a_present_and_correct_file_is_not_re_downloaded(tmp_path, served):
    """The short-circuit is what makes a re-run of a 500 GiB lock survivable.
    Counting it `present` while still spending the transfer would look
    identical in every existing assertion -- hence the request count."""
    target = tmp_path / "root" / REL
    target.parent.mkdir(parents=True)
    target.write_bytes(BODY)
    report = fetch.run(lock(tmp_path), tmp_path / "root", dry_run=False)
    assert (report.present, report.fetched) == (1, 0)
    assert served.call_count == 0, "it re-downloaded a file it had already verified"


def test_a_present_but_WRONG_file_is_replaced(tmp_path, served):
    """The mirror image, and the one that matters: a truncated or corrupted
    file on disk must not be counted `present` because the path exists."""
    target = tmp_path / "root" / REL
    target.parent.mkdir(parents=True)
    target.write_bytes(b"not the model")
    report = fetch.run(lock(tmp_path), tmp_path / "root", dry_run=False)
    assert (report.present, report.fetched) == (0, 1)
    assert target.read_bytes() == BODY


def test_a_hash_mismatch_leaves_NOTHING_behind(tmp_path, served):
    """A partial or wrong file left in place is worse than a missing one: the
    next run finds a path that exists and the run after that trusts it."""
    report = fetch.run(lock(tmp_path, sha="0" * 64), tmp_path / "root", dry_run=False)
    assert report.failed == 1
    assert any("sha256 mismatch" in line for line in report.lines)
    assert not (tmp_path / "root" / REL).exists()
    assert not list((tmp_path / "root").rglob("*.fetch-tmp"))


def test_a_failed_transfer_leaves_no_temp_file(tmp_path):
    with respx.mock:
        respx.get(URL).mock(return_value=httpx.Response(500))
        report = fetch.run(lock(tmp_path), tmp_path / "root", dry_run=False)
    assert report.failed == 1
    assert any("transfer failed" in line for line in report.lines)
    assert not list((tmp_path / "root").rglob("*.fetch-tmp"))


def test_a_404_is_a_failure_not_a_silent_skip(tmp_path):
    with respx.mock:
        respx.get(URL).mock(return_value=httpx.Response(404))
        report = fetch.run(lock(tmp_path), tmp_path / "root", dry_run=False)
    assert (report.failed, report.fetched, report.skipped) == (1, 0, 0)


def test_every_extra_install_path_gets_the_verified_bytes(tmp_path, served):
    """ComfyUI resolves some models through more than one search path and the
    lock is allowed to say so. `fetch` copies the extras ONLY on a fresh fetch,
    which is why a pruned `paths[1:]` is unrecoverable -- so the copy has to
    happen when it is the one chance."""
    second = "models/unet/m.safetensors"
    report = fetch.run(lock(tmp_path, paths=[REL, second]), tmp_path / "root",
                       dry_run=False)
    assert report.fetched == 1
    assert (tmp_path / "root" / second).read_bytes() == BODY


def test_dry_run_writes_nothing_and_asks_for_nothing(tmp_path, served):
    report = fetch.run(lock(tmp_path), tmp_path / "root", dry_run=True)
    assert (report.would, report.fetched) == (1, 0)
    assert served.call_count == 0
    assert not (tmp_path / "root").exists() or not list((tmp_path / "root").rglob("*"))


def test_an_entry_with_no_url_is_skipped_not_failed(tmp_path):
    report = fetch.run(lock(tmp_path, url=None), tmp_path / "root", dry_run=False)
    assert (report.skipped, report.failed) == (1, 0)
    assert any("no url recorded" in line for line in report.lines)


def test_an_unwritable_destination_blames_the_destination(tmp_path, served):
    """Not a transfer problem, and it is checked before the request so the
    error names the real cause rather than the source."""
    root = tmp_path / "root"
    (root / "models").mkdir(parents=True)
    (root / "models" / "loras").write_text("a FILE where the directory goes")
    report = fetch.run(lock(tmp_path), root, dry_run=False)
    assert report.failed == 1
    assert any("destination not writable" in line for line in report.lines)
    assert served.call_count == 0


def test_a_short_lock_read_is_a_hard_error_not_a_clean_run(tmp_path, served):
    """`seen != len(models)` exists because a parser that matched nothing once
    scored `0 failed`. Assert the raise, not just the counters."""
    doc = yaml.safe_load(lock(tmp_path).read_text())
    doc["models"].append({"model": "ghost"})
    p = tmp_path / "short.yaml"
    p.write_text(yaml.safe_dump(doc))
    report = fetch.run(p, tmp_path / "root", dry_run=True)
    assert report.would + report.skipped == 2, "an entry went unaccounted for"
