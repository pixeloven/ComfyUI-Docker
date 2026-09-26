# AGENTS.md — Agent Behavioral Contract

This file drives **how agents behave** on this project: autonomy, delegation, routing, planning, memory, and how to apply shared platform skills to this repo's specifics. It is deliberately **behavioral, not factual** — conventions, repository facts, and credentials live in **skills**, never here. Keeping this file behavioral is what lets it port across every project that consumes the platform.

> **One platform, many consumers.** The agent fleet and platform skills are shared (from the Crew foundation); each consumer supplies its **own** local skills for its specifics. ComfyUI-Docker is a public product — `pixeloven/ComfyUI-Docker`: GHCR images, the `comfyfetch` CLI and image, and a published skills plugin. Its specifics live in the **▸** blocks below and in its local skills (`.agents/skills/`). This `AGENTS.md` drives every harness that reads it — Claude Code, pi.dev, and OpenAI Codex — all of which can dispatch subagents.

---

## Autonomy & posture

Tool use is pre-approved. **Act, then report** — never pause to ask before:

- **Loading skills and slash commands.** Load a skill proactively the moment the task touches its domain — a skill read is cheap; re-deriving conventions costs review cycles.
- **Calling MCP tools** — the platform's federated surface and connected services.
- **Running pre-approved CLIs**, including compound commands (pipes, `&&`, `;`, command substitution, env-var prefixes).
- **Dispatching subagents** per the routing rules below. Delegation is the default for multi-step work, not an escalation.

**▸ Where the posture is set:** on Claude Code, the operator's user settings (`~/.claude/settings.json` → `permissions.defaultMode` and its `ask` list). This repo ships no project `.claude/settings.json`. Other harnesses use their own permission surface.

**▸ Ask list — still prompt before these.** Each one publishes to consumers or cannot be taken back:

- **Pushing a `v*` tag.** A tag publishes *everything* — every image, the `comfyfetch` wheel, the skills plugin — and CI creates the GitHub Release. Never create a Release by hand; see `VERSIONING.md` → *Releasing*.
- **Triggering a publishing workflow by hand** (`workflow_dispatch` on `CI` or `Nightly Upstream Build`). Both push to GHCR.
- **Pushing to `main`, force-pushing a shared branch, or deleting a branch, tag, Release or GHCR package.** Always use a branch and a PR. `--force-with-lease` on your own feature branch is fine.

Everything else: act, then report.

## Subagent delegation & routing

Delegate by work domain, without asking first. Reach for delegation by default on multi-step or multi-domain work; keep inline execution for single-file edits and quick lookups. Agents carry context via skills — you don't re-explain conventions to them.

> **Delegate on any harness that can.** Claude Code, pi.dev, and OpenAI Codex all support subagent dispatch — Codex acts on this table's instruction to delegate, so treat the table as a request, not a description. On a harness that genuinely cannot dispatch, apply the same skills **inline, solo**; the table still documents which discipline governs which kind of work.

| Task domain | Agent | Activation |
|-------------|-------|------------|
| Planning, orchestration, complex multi-step work | `lead` | dispatch |
| Write work — code, Dockerfiles, bake, workflows, docs, PRs | `implementer` | dispatch |
| Pre-merge review, convention enforcement, seam detection | `reviewer` | dispatch |
| Pre-implementation option analysis, technology evaluation | `researcher` | dispatch |
| Issue / PR intake, labeling, routing | `triage` | **trigger** |
| Reactive diagnosis, health sweeps, incidents | `investigator` | **trigger** |
| Fast read + draft (answer a question / draft a reply) | `responder` | **trigger** |

**dispatch** = you invoke it from this session. **trigger** = it should run on an event or schedule with no human in the loop, which needs infrastructure you deploy — see `activation-contracts`. None of the trigger roles is wired to an event in this repo today, so each runs only when someone dispatches it by hand.

### Quality gate (implementation work)

1. **Implement** — `implementer`
2. **Review** — `reviewer`, checking the diff against `comfyui-docker-protected-seams`
3. **Security** — `reviewer` with the `seam-detection` skill if the change touches secrets, credentials, publishing, or an external API
4. **Test** — run what the change touches. These are the commands CI runs, and each one works locally:

   | Change touches | Run |
   |---|---|
   | `services/fetch/`, `comfy.yaml`, `comfy-lock.yaml`, `locks/` | `cd services/fetch && uv run pytest -q` (add `-m "not network"` offline), then `uv run comfyfetch check ../../comfy.yaml ../../comfy-lock.yaml` |
   | `docker-bake.hcl`, `examples/` | `make validate` (bake prints `all`, and every example's `docker compose config` resolves) |
   | A Dockerfile, `entrypoint.sh`, `startup.sh` | build the affected bake group and load it (`make cuda`, `make cpu`, `make rocm`, `make xpu`, or `docker buildx bake <target> --load`), then start the matching example |
   | `services/comfy/`, `services/runtime/`, `docker-bake.hcl` | `make core-cpu`, then `make smoke` (add `SMOKE_NETWORK=host` on a host without a docker0 bridge). It boots `core-cpu` as root with `PUID`/`PGID` 1001, waits for `/system_stats`, writes to `/app/output` as that UID, and dumps `/object_info`. A `COMFYUI_VERSION` bump also regenerates `schemas/comfyui/object_info.json` with `tests/smoke/run.sh --snapshot <image>` |
   | `.github/workflows/` | `docker run --rm -v "$PWD":/repo -w /repo rhysd/actionlint:1.7.7 -color` |

   CI builds every image target on a PR that touches `services/comfy/`, `services/runtime/`, `services/mcp/`, `docker-bake.hcl` or `ci.yml`, and its `smoke-cpu` job runs `make smoke`'s script on `core-cpu`. It does not push from a PR.

### Isolation

By default a dispatched worker writes directly to the current working tree, which is what you want for in-repo work: the changes are there when it returns. Reach for your harness's isolation primitive only for genuinely parallel, independent branches — and read `orchestration-patterns` first, because each harness spells it differently and at least one defaults its branch base somewhere surprising.

## Planning model

Planning is conversational and agent-mediated, not document-driven. Plans are developed in **plan mode** with the operator, in the shape `plan-generation` describes; research is delegated to **`researcher`** (corpus-backed option analysis); designs are checked by seam audit and adversarial review (**`reviewer`**) before execution; durable design knowledge — decisions, research, reviews — is persisted to the **knowledge corpus**, never to in-repo spec documents. Work items live in the tracker.

**▸ Where plans live in this project:**

- **The plan of record is a GitHub issue** in `pixeloven/ComfyUI-Docker`. The issue body holds the approved plan (checklist first, then the detailed spec per phase). A revision edits the issue rather than opening a new one. Phases large enough for their own PR become sub-issues, and each PR says `Closes #<n>` for the phase it delivers.
- **Decisions, research and reviews** go to the knowledge corpus if your setup has one, linked to the issue. Without one, record the *why* in the issue or the PR that acted on it.
- **This repo is deployer-agnostic.** It owns the images, the runtime contract they promise (`comfyui-docker-conventions`), and generic examples. Tooling that deploys them to a particular cluster or cloud belongs to whoever runs it, and is tracked there.
- **Nothing goes in-repo as a plan.** Spec-kit's `specs/NNN-*` and its constitution were removed on purpose; do not recreate them, or any `plans/` directory. `docs/` is user-facing documentation, not a plan store.

## Memory protocol

Follow **Pre-Task Recall** before starting and **Post-Session Persistence** after, per the project's knowledge-capture local skill, with a `source_agent` set to your harness (or the dispatched agent's id). This is a platform capability — see *Fallback* for behavior when it's unavailable.

## Tools — the live catalogue is authoritative

What you can actually call is whatever your session lists right now, not what any document says. Search your available tools before concluding one doesn't exist — a tool you assumed away is indistinguishable, from the outside, from a tool that isn't there.

When a skill describes a tool that isn't in your session, or your session offers one no skill mentions, that gap is **reportable drift**, not a dead end: say what you found, use what you have, and let the mismatch be fixed rather than worked around silently.

## Interface boundaries (MCP · AXI · CLI)

Pick the class by *who the primary caller is* and *whose credentials the capability carries*. **MCP** is canonical for agents mid-task (read paths, corpus writes) and is federated — the gateway is the authorization boundary, so anything behind it is reachable by every consumer holding its access group. **AXI** is agent-facing tooling that runs locally on the machine the agent is on; it inherits that machine's credentials, which is why personal/workplace credentials stay there instead of behind a shared key. **CLI** is for humans, scripts, and CI, and for write operations the platform routes through it. When MCP and CLI both exist for a shared capability, the CLI is a thin wrapper over the MCP/library path — no parallel implementation. Prefer CLI/MCP/AXI tools over hand-rolled API calls. See `agent-platform-design` for the full decision framework.

## Applying platform skills to local specifics

**Platform skills** (shared, from the foundation) teach *general patterns*. **This project's specific values and policies** live in **local skills** in `.agents/skills/`. When you apply a platform pattern, consult the matching local skill for this repo's specifics.

**▸ Local-skills map:**

| Project-specific concern | Local skill |
|--------------------------|-------------|
| Repository layout, image and profile matrix, tag model, data and entrypoint contracts, container standards, dependency rules, and the project invariants in full | `comfyui-docker-conventions` |
| What needs owner sign-off: releases and publish paths, the ComfyUI pin, the lock and manifest format, the runtime contract, secrets, supply-chain pins, and the published skill | `comfyui-docker-protected-seams` |
| Authoring `comfy.yaml` and generating locks — the **published** product skill | `skills/comfy-manifest/SKILL.md` (read it from the path; consumers install it) |

Three declared foundation slots have no local skill here, on purpose. **`topology`**: this repo builds images and deploys nothing, so there are no nodes or addresses to record. **`agent-runtime`**: no autonomous runtime dispatches agents in this repo. **`knowledge-capture`**: the repo prescribes no corpus, because contributors bring their own setups; the tracker is the shared record, and *Fallback* covers a session with no corpus. Credential references, the `secret-paths` concern, live under *Secrets* in `comfyui-docker-protected-seams`.

## Project invariants

Each of these holds for every change. The reasons and the detail are in `comfyui-docker-conventions`.

- **Containers first, one per profile.** Every published image runs on its own. The builds are multi-stage, with the venv built in a builder stage and copied into the final stage.
- **Profiles are isolated and explicit.** A runtime difference is a bake `arg` or a documented env var, never shared state between profiles.
- **Accelerator-specific work stays in its own target.** SageAttention exists only in `complete-cuda-sm*`, and only takes effect with `--use-sage-attention`. The generic `complete-cuda` stays portable, and the CPU, ROCm and XPU images carry nothing CUDA-only.
- **User data lives on volumes, never in the image.** That covers models, outputs, custom nodes and user config, and every path can be overridden with an env var. Credentials come from the environment, resolved by host.
- **Only CI publishes.** A tag says one thing: `<sha8>`, `X.Y.Z` or `nightly`. What ComfyUI is inside is stated by the `org.opencontainers.image.version` label. `VERSIONING.md` is authoritative for what counts as major.
- **Images run under any UID.** That means PUID/PGID via `gosu` when the container starts as root, and a direct exec as non-root under Kubernetes `runAsUser`.

## Work quality

Four rules, always on. They are here rather than in a skill because a skill has to
be *triggered*, and these are true of every change — a trigger that matches
everything discriminates nothing.

- **Surface assumptions; don't hide confusion.** If multiple readings exist, name
  them rather than picking silently. If a simpler approach exists, say so. If
  something is unclear, stop and ask — a wrong assumption carried forward costs more
  than the question.
- **Smallest change that solves it.** No features beyond what was asked, no
  abstraction for single-use code, no error handling for impossible states. If it
  could be half the size, rewrite it.
- **Surgical edits.** Touch only what the request requires. Don't reformat, refactor
  or "improve" adjacent code; match the existing style even where you'd differ.
  Remove orphans *your* change created — not pre-existing dead code. **Every changed
  line should trace to the request.**
- **Verify, don't assert.** State the success criterion before starting, then check
  it. "Tests pass" means you ran them; "it loads" means you loaded it. Report what
  the check actually returned, including when it failed.

Derived from [Karpathy's observations](https://x.com/karpathy/status/2015883857489522876)
on where LLM coding agents go wrong, plus one added from this foundation's own
failures — the fourth. Bias toward caution over speed; use judgement on trivial tasks.

## Tripwires — load the skill before the action

Most conventions are reference detail — load them as soon as the task touches their domain, per *Autonomy & posture*. A few are **silent landmines** — get them wrong and it fails with no obvious error. For these, load the named skill *before* the action, every time. The skill carries the detail; this is just the trigger.

**▸ ComfyUI-Docker tripwires:**

- **Cutting a release, or changing `VERSION`** → read `VERSIONING.md` → *Releasing*, and load `comfyui-docker-protected-seams`. Creating the GitHub Release by hand makes the release job fail *after* every image has published, which leaves the Release page empty (v2.1.0 to v2.3.0 have that shape). `VERSION`, `services/fetch/pyproject.toml`, `.claude-plugin/plugin.json`, `package.json` and the `comfyfetch` entry in `services/fetch/uv.lock` must agree, and CI checks all five on every push.
- **Changing a `comfyfetch` verb, a flag, or the manifest or lock format** → update `skills/comfy-manifest/SKILL.md` in the same change, and load `comfyui-docker-protected-seams`. That skill ships to every consumer on the next tag, and no test compares it with the CLI. When it names a flag the code no longer has, an agent calls it and reports comfyfetch as broken. A format break is a **major** version.
- **Bumping `COMFYUI_VERSION`, the torch index, the CUDA base image, or Python** → load `comfyui-docker-conventions`. The SageAttention wheels are built for exactly cu130, torch 2.13.0 and cp312, while core installs whatever torch the index serves. When those diverge, only the separately built `cuda-arch` group fails, so the generic CUDA images keep publishing while the `cuda-sm*` tags quietly stop moving.
- **Editing `entrypoint.sh`, `startup.sh`, or the permission steps in `dockerfile.comfy.core`** → load `comfyui-docker-conventions`. The arbitrary-UID contract only fails at runtime, under a UID nobody tested. The volume-root `chown` is deliberately non-recursive, because model stores run to terabytes.
- **Adding an agent skill** → a skill for agents working *on* this repo goes in `.agents/skills/<name>/`, symlinked from `.claude/skills/<name>`. A skill for *consumers* goes in `skills/<name>/`. Anything under `skills/` publishes to every consumer on the next tag.
- **Running `uv` in `services/fetch`** → stage files by name rather than `git add -A`. `uv run` creates `services/fetch/.venv`; `.gitignore` covers it, but a stray lockfile or build output may not be.

## Fallback — when the platform is unavailable

The platform (corpus, LLM gateway, cluster) is the **default path — reach for it first**, and let an actual failed call, not an assumption, establish that something is unavailable. Once a capability is confirmed unreachable, degrade gracefully rather than fail — and say what you skipped:

- **No corpus / memory substrate** → work from the repo, git history, and the web; skip Pre-Task Recall and Post-Session persistence (note it).
- **No MCP gateway** → fall back to direct CLIs.
- **No cluster / live-infra access** → operate on the repo (code, Dockerfiles, bake, workflows); defer anything needing live infra and say so.

Every role keeps its core value on a bare repo — `reviewer` reviews the diff, `researcher` evaluates from web + repo, `implementer` edits code — and sharpens that with platform capabilities wherever they're reachable.

**▸ ComfyUI-Docker:** no GPU locally → `make core-cpu`, then `make smoke`, exercises the entrypoint, the startup and a data mount the way CI's `smoke-cpu` job does, and the CPU example (`make test-cpu`) covers the rest of the mounts. Only `core-cpu` is booted, locally or in CI. GPU-only behavior is verified by CI's image builds and nothing boots those images, so say so.

## Skills — how agents find them

Your harness lists every installed skill, with its description, before the first turn — foundation skills and this repo's own, together. **That listing is the discovery mechanism**, so there is no index to write or maintain here: put a skill where the harness looks and agents can find it. Load one the moment the work touches its domain; loading is cheap, re-deriving conventions is not. Where a local skill shares a name with a foundation one, what happens depends on the harness: in pi's flat namespace the local copy shadows the foundation's outright; Claude Code and Codex namespace the plugin copy as `crew:skill`, so both stay visible and you pick. Don't rely on shadowing to disable a foundation skill.

The concern → local skill mapping under *Applying platform skills to local specifics* above is the only routing worth writing down, because it encodes a judgement the descriptions can't make for you. Don't restate the catalogue here — it goes stale the day someone adds a skill.

**Layout is what fails silently, not indexing.** Every skill is a directory containing `SKILL.md`, named for the skill. There is no flat form anywhere:

| Harness | Reads | Needs |
|---|---|---|
| pi.dev | `.agents/skills/<name>/SKILL.md` | nothing — walks cwd to git root |
| Codex | `.agents/skills/<name>/SKILL.md` | nothing |
| Claude Code | `.claude/skills/<name>/SKILL.md` | a symlink to the above |

So one canonical tree serves all three:

```sh
.agents/skills/<name>/SKILL.md                          # the real file
ln -s ../../.agents/skills/<name> .claude/skills/<name> # Claude Code
```

Claude Code is the only harness that does not read `.agents/`, and it requires the **directory** form — a flat `.claude/skills/<name>.md` is invisible to it with no error.

**▸ Two skill trees, two audiences.** `.agents/skills/` is for agents working *on* this repo, and no package manifest ships it. `skills/` is the *product*: `.claude-plugin/plugin.json` (`"skills": "./skills"`) and `package.json` (`pi.skills`) publish it to Claude Code, Codex and pi consumers. `skills/README.md` covers that publishing flow.

**Verify against the running harness, not the file tree** — the tree looks right in exactly the case that fails. For Codex, `codex debug prompt-input` renders the model-visible prompt with no API call. A fresh `claude -p`, `pi -p`, or `codex exec` process is billed and requires explicit approval. Run `doctor` to compare what this harness actually loaded against what's on disk and to mark other harnesses untested.

Run layout validation from the absolute resolved Crew package root, never a consumer-relative `scripts/` path: `python3 /absolute/resolved/crew/root/scripts/check_skill_layout.py /absolute/consumer/repo`.

Because discovery runs entirely on descriptions, a skill's `description` is its whole interface: say what it's for and when to reach for it, and front-load the discriminating words. A skill nothing matches against is a skill nobody loads.

## Git

- Use your harness's GitHub credential helper; never embed tokens in remote URLs.
- Commit format: `<type>(<scope>): <subject>` (feat, fix, docs, refactor, chore, ci, test) — Conventional Commits. Use `gh` for PRs, issues, releases.

**▸ ComfyUI-Docker:** remote `origin` is `https://github.com/pixeloven/ComfyUI-Docker.git`; never push directly to `main` — branch `<type>/<short-desc>` and open a PR (a merge to `main` publishes the `*-<sha8>` and `*-latest` images). A `no-mistakes` remote is configured for the validation gate; load the `no-mistakes` skill when shipping through it. Recent history shows each releasable PR carrying its own version bump in all five files that state the version, plus a dated `## X.Y.Z — YYYY-MM-DD` section in `CHANGELOG.md`. After the PR merges, the tag is pushed. The release job refuses a version whose changelog section is missing or still marked unreleased.
