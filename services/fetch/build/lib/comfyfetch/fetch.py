"""Materialise the models a lock declares, verifying every one.

  A fetch is verified, not trusted. A wrong-but-plausible model file is worse
  than a missing one -- a missing file fails loudly at load, a wrong one renders
  subtly wrong images forever with no error anywhere.

  A partial file is never left in place. Downloads land on a temporary sibling
  and are renamed only after the hash matches, so an interrupted run leaves the
  workspace exactly as it found it.

Usage: comfy-fetch <comfy-lock.yaml> <comfyui-root> [--apply]

Paths in the lock are relative to the ComfyUI ROOT (they begin `models/`), so
the second argument is the workspace root, not the models directory.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import shutil
import sys

from . import http, lockfile
from .auth import AuthMap

CHUNK = 1 << 20


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


class Report:
    def __init__(self) -> None:
        self.present = self.fetched = self.skipped = self.failed = self.would = 0
        self.bytes = 0
        self.lines: list[str] = []

    def render(self, dry_run: bool) -> str:
        out = list(self.lines)
        out.append(f"present:     {self.present}")
        if dry_run:
            out.append(f"would fetch: {self.would}")
        else:
            out.append(f"fetched:     {self.fetched}")
            if self.bytes:
                out.append(f"written:     {self.bytes // 1_000_000} MB")
        out.append(f"skipped:     {self.skipped}")
        out.append(f"failed:      {self.failed}")
        if dry_run:
            out.append("dry run — re-run with --apply to download")
        return "\n".join(out)


def _fetch_one(model: dict, root: pathlib.Path, auth: AuthMap, *, dry_run: bool,
               report: Report) -> None:
    name = model.get("model") or "<unnamed>"
    rel = lockfile.lock_path(model)
    url = model.get("url")
    want = lockfile.sha256_of(model)
    paths = [p["path"] for p in (model.get("paths") or [])]

    if not rel:
        report.lines.append(f"  SKIP    {name}: no path recorded")
        report.skipped += 1
        return

    target = root / rel
    if target.is_file() and want and sha256_file(target).lower() == want:
        report.present += 1
        return
    if not url:
        report.lines.append(f"  SKIP    {name}: no url recorded")
        report.skipped += 1
        return
    if not want:
        # Fetching this would put unverified bytes in the workspace under the
        # guise of a verified run.
        report.lines.append(
            f"  SKIP    {name}: no SHA256 in the lock, refusing to fetch unverified")
        report.skipped += 1
        return
    if dry_run:
        report.would += 1
        return

    missing = auth.missing_var_for(url)
    hint = f" (${missing} is not set)" if missing else ""

    tmp = target.with_name(target.name + ".fetch-tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.touch()
    except OSError as exc:
        # Not a transfer problem. Checked before the request so the error names
        # the real cause rather than blaming the source.
        report.lines.append(f"  FAILED  {name}: destination not writable: {exc.strerror or exc}")
        report.failed += 1
        return

    try:
        with http.request(url, token=auth.token_for(url), timeout=300) as resp, \
                open(tmp, "wb") as out:
            shutil.copyfileobj(resp, out, CHUNK)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        report.lines.append(f"  FAILED  {name}: transfer failed: {type(exc).__name__}{hint}")
        report.failed += 1
        return

    if sha256_file(tmp).lower() != want:
        tmp.unlink(missing_ok=True)
        report.lines.append(f"  FAILED  {name}: sha256 mismatch{hint}")
        report.failed += 1
        return

    size = tmp.stat().st_size
    tmp.replace(target)
    report.bytes += size
    report.fetched += 1

    # Additional install paths get a copy of the verified bytes: ComfyUI
    # resolves some models through more than one search path, and the lock is
    # allowed to say so.
    for extra in paths[1:]:
        dest = root / extra
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(target, dest)


def run(lock_path: pathlib.Path, root: pathlib.Path, *, dry_run: bool) -> Report:
    doc = lockfile.load(lock_path)
    auth = AuthMap.from_document(doc)
    models = doc.get("models") or []
    report = Report()
    for model in models:
        _fetch_one(model, root, auth, dry_run=dry_run, report=report)
    seen = report.present + report.fetched + report.skipped + report.failed + report.would
    if seen != len(models):
        # Reading fewer entries than the lock declares must never be reported as
        # a clean run: that is how a parser that matched nothing scored 0 failed.
        raise SystemExit(
            f"accounted for {seen} entries but the lock declares {len(models)}")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="comfy-fetch", description=__doc__)
    ap.add_argument("lock", type=pathlib.Path)
    ap.add_argument("root", type=pathlib.Path)
    ap.add_argument("--apply", action="store_true",
                    help="actually download; without it nothing is written")
    args = ap.parse_args(argv)
    if not args.lock.is_file():
        print(f"no such lock: {args.lock}", file=sys.stderr)
        return 2
    report = run(args.lock, args.root, dry_run=not args.apply)
    print(report.render(dry_run=not args.apply))
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
