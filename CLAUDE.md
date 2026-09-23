# CLAUDE.md

Guidance for Claude Code in this repo. **Behavior, delegation, planning, memory, tripwires and the platform↔local skill map live in [AGENTS.md](AGENTS.md)** (imported below), which pi and Codex read directly. This file adds only Claude-specific harness detail. Repository facts live in the local skills `comfyui-docker-conventions` and `comfyui-docker-protected-seams`.

@AGENTS.md

## Claude Code specifics

- **Permissions** come from your user settings (`~/.claude/settings.json`). This repo ships no project `.claude/settings.json`.
- **Local skills** are symlinks: `.claude/skills/<name>` → `../../.agents/skills/<name>`. Edit the file under `.agents/skills/`. A new skill needs both the directory and the symlink, or Claude Code will not see it.
- **This checkout does not load the published skill.** `skills/comfy-manifest/` is the product, and consumers install it through `.claude-plugin/`. A session sees it only if the `comfyui-docker@pixeloven` plugin is installed, and then at the installed version, not your working copy. Read it by path when a change touches `comfyfetch` or the manifest format.
