"""Resolve, verify and materialise ComfyUI model locks.

Ported from shell. The behaviours below were each learned from a failure and are
covered by tests; changing any of them is a behaviour change, not a refactor.

- **No partial output.** A resolve that cannot resolve every source writes no
  lock at all. A lock that looks complete but is short is worse than none.
- **Every failure in one pass.** One dead source must not cost the other 160
  files their resolution, nor hide the next problem behind it.
- **Verified, never trusted.** Bytes are hashed before they are moved into
  place, and an entry with no SHA256 is refused rather than fetched unverified.
- **A missing credential does not block a public file.** It is recorded and
  named only if the fetch then fails.
"""

__all__ = ["auth", "check", "fetch", "lockfile", "profiles", "resolve"]
