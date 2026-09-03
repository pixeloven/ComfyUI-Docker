# Skills

Agent-facing knowledge for consuming this repository, published as a Claude Code
plugin and a pi package from the same source.

A consumer installs it rather than copying it — a copied skill is a fork that
drifts silently, and the copy always wins over the published one.

**Claude Code** — `.claude/settings.json`:

```jsonc
"extraKnownMarketplaces": {
  "comfyui-docker": { "source": { "source": "github", "repo": "pixeloven/ComfyUI-Docker" } }
},
"enabledPlugins": { "comfyui-docker@comfyui-docker": true }
```

**pi** — `.pi/settings.json`:

```jsonc
"packages": ["git:github.com/pixeloven/ComfyUI-Docker@v0.1.0"]
```

Pin by tag. The plugin version tracks the repository's `VERSION` file, released
by the same `v*.*.*` tag that publishes the images — one version line, not a
third one to keep in step.

Discovery is the runtime's job: both harnesses list every loaded skill with its
description, so a skill added here becomes reachable with no consumer edited and
no index maintained.
