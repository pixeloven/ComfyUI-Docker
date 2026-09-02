"""Resolve comfy.yaml (intent) into comfy-lock.yaml (resolution).

The manifest/lock step, the same one `npm install` performs: the manifest says
`hf:owner/repo` at `revision: main`, and the lock records the exact commit, the
exact URL, and the sha256 of the bytes that commit serves.

It talks to the network and is NOT idempotent across time: re-resolving a moving
ref after upstream moves is SUPPOSED to produce a new commit and a new hash.
That is the point, which is why CI never re-resolves as a drift check --
check-lock compares manifest against lock offline instead.

Resolution needs no credentials for public sources: HuggingFace returns hashes
in headers, Civitai's model-versions endpoint is public, and GitHub's release
API is too. Tokens are needed to FETCH, and to read a gated repo.

Usage: comfy-resolve <comfy.yaml> [--profile NAME] [--from-lock LOCK]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import tempfile
import urllib.error
import urllib.parse

from . import http, lockfile, profiles
from .auth import AuthMap

HF = "https://huggingface.co"


class Unresolved(Exception):
    """A source that could not be resolved. Collected, never fatal on its own."""


def _quote(path: str) -> str:
    """Percent-encode a URL path, leaving `/` intact.

    HuggingFace filenames routinely contain spaces and parentheses --
    "Anime v1.3 (1).safetensors" is a real one. An unencoded space produces a
    request that fails in a way that reads as a missing file.
    """
    return urllib.parse.quote(path, safe="/")


def _hf(repo: str, revision: str, file: str, auth: AuthMap) -> tuple[str, str]:
    """(url pinned to a commit, sha256) for a HuggingFace file."""
    url = f"{HF}/{repo}/resolve/{revision}/{_quote(file)}"
    headers = http.head_headers(url, token=auth.token_for(url))
    commit = headers.get("x-repo-commit")
    etag = (headers.get("x-linked-etag") or "").strip('"')
    if not commit or not etag:
        missing = auth.missing_var_for(url)
        why = f"gated (${missing} is not set)" if missing else \
              "not found, or you lack access to a gated repo"
        raise Unresolved(f"hf:{repo}@{revision}/{file}: {why}")
    # The lock pins the COMMIT, never the moving ref it resolved from.
    return f"{HF}/{repo}/resolve/{commit}/{_quote(file)}", etag.lower()


def _github(repo: str, tag: str, asset: str, auth: AuthMap) -> tuple[str, str | None]:
    """(download url, sha256 or None) for a GitHub release asset."""
    api = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    try:
        with http.request(api, token=auth.token_for("https://github.com/")) as resp:
            release = json.load(resp)
    except urllib.error.HTTPError as exc:
        raise Unresolved(f"gh:{repo}@{tag}: release not found (HTTP {exc.code})") from exc
    for a in release.get("assets") or []:
        if a.get("name") == asset:
            digest = a.get("digest") or ""
            sha = digest[7:] if digest.startswith("sha256:") else None
            return a["browser_download_url"], sha
    raise Unresolved(f"gh:{repo}@{tag}: no asset named {asset}")


def _civitai(version_id: str) -> tuple[str, str]:
    api = f"https://civitai.com/api/v1/model-versions/{version_id}"
    try:
        with http.request(api) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        raise Unresolved(
            f"civitai:{version_id}: not found (deleted upstream, or the version "
            f"id is wrong) — HTTP {exc.code}") from exc
    files = data.get("files") or []
    if not files:
        raise Unresolved(f"civitai:{version_id}: the version has no files")
    sha = ((files[0].get("hashes") or {}).get("SHA256") or "").lower()
    if not sha:
        raise Unresolved(f"civitai:{version_id}: no SHA256 in the API response")
    return files[0]["downloadUrl"], sha


def _download_and_hash(url: str, auth: AuthMap) -> str:
    with tempfile.NamedTemporaryFile() as tmp:
        with http.request(url, token=auth.token_for(url), timeout=600) as resp:
            h = hashlib.sha256()
            for block in iter(lambda: resp.read(1 << 20), b""):
                h.update(block)
                tmp.write(block)
    return h.hexdigest()


def _resolve_file(entry: dict, auth: AuthMap) -> dict:
    source = entry["source"]
    file = entry.get("file") or ""
    stated = (entry.get("sha256") or "").lower()

    if source.startswith("hf:"):
        if not file:
            raise Unresolved(f"{source}: hf source needs `file`")
        url, sha = _hf(source[3:], entry.get("revision", "main"), file, auth)
        name = pathlib.PurePosixPath(file).name
    elif source.startswith("gh:"):
        spec = source[3:]
        repo, _, tag = spec.rpartition("@")
        if not file:
            raise Unresolved(f"{source}: gh source needs `file` (the asset name)")
        url, sha = _github(repo, tag, file, auth)
        if not sha:
            sha = stated or _download_and_hash(url, auth)
        name = file
    elif source.startswith("civitai:"):
        url, sha = _civitai(source.split(":", 1)[1])
        name = entry.get("as") or pathlib.PurePosixPath(
            urllib.parse.urlsplit(url).path).name
    elif source.startswith(("http://", "https://")):
        # Nothing about a bare URL can be resolved from headers, so the manifest
        # must state the hash. Refusing is the honest outcome: a lock entry with
        # no hash produces a fetch that verifies nothing.
        if not stated:
            raise Unresolved(f"{source}: a direct URL needs `sha256` in the manifest")
        url, sha = source, stated
        name = pathlib.PurePosixPath(urllib.parse.urlsplit(source).path).name
    else:
        raise Unresolved(f"{source}: unknown source scheme")

    model = {
        "model": entry.get("as") or name,
        "url": url,
        "paths": [{"path": lockfile.install_path(entry)}],
        "hashes": [{"hash": sha, "type": "SHA256"}],
    }
    if entry.get("type"):
        model["type"] = entry["type"]
    return model


def _selected(manifest: dict, profile: str | None) -> list[dict]:
    models = manifest.get("models") or []
    if not profile:
        return models
    names = set(profiles.expand(manifest, profile))
    return [m for m in models if m["name"] in names]


def from_lock(manifest: dict, profile: str, parent: dict) -> tuple[dict | None, list[dict]]:
    """Select from an existing lock instead of resolving.

    Entries are copied VERBATIM, so a derived lock is a strict subset of its
    parent and every profile pins identical commits. Re-resolving each
    independently could legitimately pin DIFFERENT ones, because a moving
    revision is supposed to advance.
    """
    wanted = [lockfile.install_path(f)
              for m in _selected(manifest, profile) for f in m["files"]]
    have = {lockfile.lock_path(m): m for m in parent.get("models") or []}
    missing = [p for p in wanted if p not in have]
    if missing:
        raise Unresolved(
            "the parent lock is stale; re-resolve it before deriving from it:\n"
            + "\n".join(f"  {p}" for p in missing))
    return parent.get("auth"), [have[p] for p in wanted]


def resolve_all(manifest: dict, profile: str | None,
                on_resolved=None) -> tuple[list[dict], list[str]]:
    """(models, failures). Failures are COLLECTED, never fatal on their own.

    One dead source must not cost the other 160 files their resolution, nor hide
    the next problem behind it. The caller decides what to do with a non-empty
    failure list -- and must not write a lock, because a lock that looks complete
    but is short is worse than none.
    """
    auth = AuthMap.from_document(manifest)
    models: list[dict] = []
    failures: list[str] = []
    for capability in _selected(manifest, profile):
        for entry in capability["files"]:
            try:
                model = _resolve_file(entry, auth)
            except Unresolved as exc:
                failures.append(str(exc))
                if on_resolved:
                    on_resolved(capability["name"], None, str(exc))
                continue
            models.append(model)
            if on_resolved:
                on_resolved(capability["name"], model["model"], None)
    return models, failures


def declared_count(manifest: dict, profile: str | None) -> int:
    return sum(len(m["files"]) for m in _selected(manifest, profile))
