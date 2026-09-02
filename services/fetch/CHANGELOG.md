# Changelog

Semantic versioning. A **major** bump is a break in the lock or manifest
*format* — consumers pin those, so a format change is not a patch however small
the diff looks.

Consumers pin the image by **digest**; these versions say whether a digest
change was a patch or a break, which a commit-sha tag cannot.

## 0.2.0 — unreleased

- `fetch` reports per-file progress on stderr. A 25 GB fetch that printed
  nothing until it finished was indistinguishable from a hung job, which is
  exactly how the first real in-cluster run looked. Progress stays on stderr so
  `fetch | grep` and `--output json` are unaffected.

## 0.1.0 — unreleased

First versioned release. The tooling itself is in use: Harmony resolves and
verifies 161 model files with it.

- `comfyfetch resolve` — manifest to lock, pinning moving refs to commits.
  Sources: `hf:`, `gh:`, `civitai:` and direct URLs. `--from-lock` derives a
  profile's lock from a parent so every profile pins identical commits.
- `comfyfetch fetch` — lock to disk, verifying every file against its sha256.
  Refuses an entry with no hash rather than fetching it unverified.
- `comfyfetch check` — manifest and lock agree, offline.
- Host-keyed credentials from an `auth` map of `${ENV_VAR}` references; the
  schema rejects literals so a token cannot be committed.
- Credentials are stripped on a cross-origin redirect, matching curl. HuggingFace
  redirects `/resolve/` to a different host, so this is what keeps an account
  token off the CDN.
