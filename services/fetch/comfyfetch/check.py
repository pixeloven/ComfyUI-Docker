"""Is a lock consistent with its manifest?

Manifest declares intent; the lock records resolution. This checks they still
describe the same set of files, OFFLINE.

Deliberately NOT "re-resolve and diff". A moving `revision:` is SUPPOSED to
resolve to a new commit once upstream moves, so a re-resolve gate would fail for
the one reason that is not a mistake -- and would need network access in CI to
do it. Hash changes come from a deliberate resolve run, reviewed like any diff.

Driven by `comfyfetch check`; see cli.py for the interface.
"""

from __future__ import annotations

from . import lockfile, profiles


def check(manifest: dict, lock: dict, profile: str | None = None) -> tuple[list[str], int, int]:
    """(problems, declared, locked)."""
    problems = [f"BAD PROFILE {p}" for p in profiles.validate_all(manifest)]

    models = manifest.get("models") or []
    if profile:
        names = set(profiles.expand(manifest, profile))
        models = [m for m in models if m["name"] in names]

    declared = sorted({lockfile.install_path(f) for m in models for f in m["files"]})
    locked = sorted({p for m in (lock.get("models") or [])
                     if (p := lockfile.lock_path(m))})

    # Two empty sides compare equal. Without this a broken selection reports the
    # gate as PASSING.
    if not declared:
        problems.append("GATE BROKEN: the manifest declares no files")
    if not locked:
        problems.append("GATE BROKEN: the lock contains no entries")

    problems += [f"NOT LOCKED   {p}" for p in declared if p not in set(locked)]
    problems += [f"NOT DECLARED {p}" for p in locked if p not in set(declared)]
    problems += [f"NO SHA256    {m.get('model')}" for m in (lock.get("models") or [])
                 if not lockfile.sha256_of(m)]
    return problems, len(declared), len(locked)
