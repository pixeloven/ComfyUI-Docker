# Changelog

Everything this repo publishes, under one version: the ComfyUI images
(`complete`, `core`, `runtime`), the `mcp` image, the `comfyfetch` image **and
wheel**, and the skills plugin. Released as `vX.Y.Z`; the version lives in
`VERSION`, and every manifest that states it must agree.

This is **our packaging version**, not what is inside the image. `COMFYUI_VERSION`
is pinned in `docker-bake.hcl`, published alongside, and moves independently —
see `VERSIONING.md`.

## 1.0.0 — 2026-09-04

**One release for everything.** Previously the repo published two independent
lines, and a `comfyfetch/v*` tag released only the CLI. Neither entry on the
releases page described the repo, and GitHub marked whichever shipped last as
"Latest" — so `comfyfetch 0.2.0` appeared to supersede `ComfyUI images 0.1.0`.
They were unrelated axes, and no consumer could be expected to work that out.

A `v1.2.3` tag now builds and publishes everything from one commit, in one
release: image digests, the `comfyfetch` wheel with its checksum and build
provenance, and the skills plugin.

- The version lives in `VERSION`. `pyproject.toml` and `.claude-plugin/plugin.json`
  must state the same number, checked on every push rather than at release time.
- `comfyfetch` is versioned with the repo. Its version no longer says "what
  changed in the CLI" — this changelog does. Install it from the release:
  `uv tool install <release-url>/comfyfetch-1.0.0-py3-none-any.whl`.
- A release builds every image rather than reusing digests, so everything in a
  release provably comes from the tagged commit.

### Before 1.0.0

Two release lines existed. `v0.1.0` published the images; `comfyfetch/v0.2.0`
published the CLI. Both remain, and their artifacts stay valid — the wheel and
its attestation still verify. Nothing supersedes them; they simply describe less
than a release does now.

## 0.1.0 — 2026-09-03

First versioned release. The images have been in use for some time; what is new
is that a consumer can now name a version rather than a commit sha.

- `runtime`, `core` and `complete` for CUDA, CPU, ROCm and XPU, plus
  architecture-specific `complete` variants (sm80, sm86, sm89, sm90, sm120)
  carrying SageAttention wheels built for the matching ABI.
- `mcp` — the ComfyUI MCP bridge.
- Compose examples under `examples/`, including the model-fetch profile.
- The `comfyui-docker` skills plugin (`skills/comfy-manifest`), installable on
  Claude Code and pi. Its version tracks this line.

## comfyfetch, before it shared this version

Kept so the CLI's own history is not lost to the consolidation.

### comfyfetch 0.2.0 — 2026-09-03

- `fetch` reports per-file progress on stderr. A 25 GB fetch that printed
  nothing until it finished was indistinguishable from a hung job, which is
  exactly how the first real in-cluster run looked. Progress stays on stderr so
  `fetch | grep` and `--output json` are unaffected.

### comfyfetch 0.1.0 — never published

Superseded by 0.2.0 before any tag was cut, so no `comfyfetch/v0.1.0` exists and
none will. The entry stays because the work below is what 0.2.0 first shipped.

The tooling itself was already in use: Harmony resolves and verifies 161 model
files with it.

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
