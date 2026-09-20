# Skills

Agent-facing knowledge for consuming this repository, published to **Claude
Code, pi and Codex from one source** — `skills/`, one directory per skill,
each holding a `SKILL.md`.

A consumer installs it rather than copying it: a copied skill is a fork that
drifts silently, and the copy always wins over the published one.

Pin by tag. The version tracks the repository's `VERSION` file, released by the
same `v*.*.*` tag that publishes the images — one version line, not a third one
to keep in step.

| Harness | What it reads | Consumer config |
|---|---|---|
| Claude Code | `.claude-plugin/plugin.json` → `skills` | `.claude/settings.json` (below) |
| pi | `package.json` → `pi.skills` | `.pi/settings.json` (below) |
| Codex | `.claude-plugin/plugin.json` → `skills`, via the marketplace | `codex plugin add` (below) |

**Claude Code** — `.claude/settings.json`:

```jsonc
"extraKnownMarketplaces": {
  "pixeloven": { "source": { "source": "github", "repo": "pixeloven/marketplace" } }
},
"enabledPlugins": { "comfyui-docker@pixeloven": true }
```

**pi** — `.pi/settings.json`:

```jsonc
"packages": ["git:github.com/pixeloven/ComfyUI-Docker@v2.1.0"]
```

**Codex**:

```sh
codex plugin marketplace add pixeloven/marketplace
codex plugin add comfyui-docker@pixeloven
```

## The three keys, and what breaks without each

Each harness reads a DIFFERENT file, and every failure here is silent — the
install succeeds and the skill is simply absent.

1. `.claude-plugin/plugin.json` must state `"skills": "./skills"`. Claude Code
   infers `skills/` by convention, so it works without the key; **Codex's
   manifest path does not** and installs zero skills without it. That is the
   shape of this bug class: the harness you develop on stays green.
2. `package.json` must state `"pi": { "skills": ["./skills"] }`. pi reads no
   other manifest, so without it `packages: ["git:github.com/…"]` clones the
   repo and loads nothing.
3. `pixeloven/marketplace` must carry an entry for this repo, pinned by SHA.
   `codex plugin add` resolves through the catalogue, not through this repo.

## Verify against a RUNNING harness, never the tree

The tree looked correct in all three cases above while two of the three
harnesses loaded nothing. Each harness lists what it actually loaded:

```sh
codex debug prompt-input "hi"   # native introspection, no model call, free
claude -p "/context"            # a SEPARATE process: skills load at session start
pi --print "list your skills"
```

Description text is the always-on cost — bodies load on demand, descriptions do
not. Codex budgets the catalogue and shortens descriptions to fit without an
ellipsis, so front-load the trigger clause in the first ~100 characters.
