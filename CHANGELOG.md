# Changelog

The ComfyUI image family — `complete`, `core`, `runtime`, `mcp` — and the
skills plugin, which ships on this line rather than carrying a third version to
keep in step. Released as `vX.Y.Z`; the version lives in `VERSION`.

This is **our packaging version**, not what is inside the image. `COMFYUI_VERSION`
is published alongside it and moves independently; see `VERSIONING.md`.

The `comfyfetch` CLI and its image are a separate line with its own changelog at
`services/fetch/CHANGELOG.md`.

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
