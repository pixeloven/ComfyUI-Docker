# Changelog

Everything this repo publishes, under one version: the ComfyUI images
(`complete`, `core`, `runtime`), the `mcp` image, the `comfyfetch` image **and
wheel**, and the skills plugin. Released as `vX.Y.Z`; the version lives in
`VERSION`, and every manifest that states it must agree.

This is **our packaging version**, not what is inside the image. `COMFYUI_VERSION`
is pinned in `docker-bake.hcl`, published alongside, and moves independently —
see `VERSIONING.md`.

## 3.0.0 — 2026-09-25

### Breaking: the `mcp` image is now a hardened artokun/comfyui-mcp

`ghcr.io/pixeloven/comfyui/mcp` keeps its name, its port (`9000`), its path
(`/mcp`) and `COMFYUI_URL`, but the server inside is new, and it **requires a
token**. It packages [artokun/comfyui-mcp](https://github.com/artokun/comfyui-mcp)
`0.52.203` from npm, pinned by `ARTOKUN_VERSION` in `docker-bake.hcl`, on
`node:22-slim`. It replaces joenorton/comfyui-mcp-server, which couldn't run an
arbitrary workflow, inspect nodes or install anything, and served an
unauthenticated endpoint.

It was the only server that passed all four tasks of the Phase 1 evaluation
(build and run a workflow, install a pinned node pack and use it, answer
questions about the live node set, report a real validation error) against a
containerized ComfyUI ([#102](https://github.com/pixeloven/ComfyUI-Docker/issues/102)).
It's the interim default until
[#103](https://github.com/pixeloven/ComfyUI-Docker/issues/103) decides the long
term.

**To upgrade:**

1. **Set `COMFYUI_MCP_HTTP_TOKEN`** to a long random secret, such as
   `openssl rand -hex 32`, from your secret store. Without it the container exits
   1 at start with `Refusing to start: HTTP MCP transport bound on non-loopback
   host 0.0.0.0 WITHOUT an auth token`.
2. **Send the token from every client**, as `Authorization: Bearer <token>` or
   `X-API-Key: <token>`. For Claude Code: `claude mcp add --transport http comfyui
   http://<host>:9000/mcp --header "Authorization: Bearer <token>"`. A request
   without it gets `401`.
3. **Update anything that names a tool.** The tool names are all different, for
   example `get_system_stats`, `create_workflow`, `enqueue_workflow`,
   `install_custom_node` and `restart_comfyui`. Prompts, allow lists and scripts
   written for the old server's tools won't find them.
4. **Keep ComfyUI-Manager on** (`COMFY_ENABLE_MANAGER=true`, the default) if agents
   should restart ComfyUI: the server restarts it through Manager's reboot
   endpoint.

What the image sets, so a deployment can't forget it (the
[README](services/mcp/README.md) explains each):

- A token is required. The server binds `0.0.0.0` and refuses to start without one.
- Self-update is off (`COMFYUI_MCP_AUTO_UPDATE_DISABLE=1`). Upstream otherwise
  installs `comfyui-mcp@latest` over itself at startup.
- Panel auto-install is off (`COMFYUI_MCP_PANEL_AUTOINSTALL=0`). Upstream otherwise
  installs its own custom node into ComfyUI.
- `runpod*`, `train_*`, `report_issue` and `apps` are denied
  (`COMFYUI_MCP_TOOL_DENY`). Those spend money, need Docker, or publish to the
  author's services. The other 34 tools stay.
- ComfyUI is always treated as remote (`COMFYUI_MCP_FORCE_REMOTE=1`), so
  `restart_comfyui` goes through Manager's reboot endpoint with no shell command.
- The build fails unless `ARTOKUN_VERSION` is an exact version, and a build-time
  probe checks that the server refuses to start without a token and answers an
  MCP `initialize` with one.

Two limits to know about:

- **Node installs need Manager to accept them.** Manager refuses installs over HTTP
  when ComfyUI listens on all interfaces, which is how our images start it. Until
  [#125](https://github.com/pixeloven/ComfyUI-Docker/issues/125) decides the image
  side, `install_custom_node` works only when ComfyUI listens on loopback and shares
  the MCP container's network, or when Manager's security config allows it.
- **ComfyUI still has no authentication.** The token protects the MCP server, not
  ComfyUI's port.

Run the container with an init process (`init: true` in Compose, `docker run
--init`), or every stop waits out the timeout: the server doesn't handle `SIGTERM`
as PID 1.

`services/mcp/constraints.txt` and the `sed` patch to upstream's `server.py` are
gone, with the Python server they existed for.

## 2.4.2 — 2026-09-25

### Any `PUID` and `PGID` work when the container starts as root

The image has a user and group named `comfy` as 1000:1000. When `PUID` or
`PGID` named an ID the image did not have, the entrypoint tried to create a
second `comfy`, which failed, and the container exited at start. That broke the
`PUID=3000 PGID=3000` example in the running guide, and NAS IDs such as
1026:100, where the group exists and the user doesn't.

A user or group that has to be created is now named for its ID, such as
`comfy-3000`, with home `/app`. An ID the image already has is reused as before,
including that user's home directory.

### Hardening

Defense in depth. Nothing you configure changes, except:

- The entrypoint moved from `/app/entrypoint.sh` to `/usr/local/bin/entrypoint.sh`,
  owned by root. It is still the image's `ENTRYPOINT`, so only a deployment that
  names the old path explicitly (an `--entrypoint` or a Kubernetes `command:`)
  needs to change.

Also in this release:

- The core image drops setuid and setgid bits, which nothing in the image needs,
  and the `core` and `complete` builds fail if one comes back or if any file
  carries capabilities.
- The entrypoint's setup steps were hardened.
- Every example runs `comfyui` and `fetch` with `no-new-privileges:true`.

### Note: building `dockerfile.comfy.core` needs `COMFYUI_VERSION`

Not new in this release, but missing from the 2.4.1 notes: since #109 the
Dockerfile has no default `COMFYUI_VERSION`, and a build without one stops with
`COMFYUI_VERSION is required`. Build through `docker buildx bake`, which sets
the pin, or pass `--build-arg COMFYUI_VERSION=<ref>`.

## 2.4.1 — 2026-09-24

### `mcp` starts again: the MCP SDK is held below 2

`ghcr.io/pixeloven/comfyui/mcp` crashed on start with `ModuleNotFoundError: No
module named 'mcp.server.fastmcp'`. Upstream `joenorton/comfyui-mcp-server`
v1.1.1 asks only for `mcp>=0.9.0`, so every build took the newest SDK. mcp 2.x
removed `mcp.server.fastmcp`, which upstream imports. The pin on upstream
(`MCP_VERSION`) held, but its dependency drifted underneath it
([joenorton/comfyui-mcp-server#18](https://github.com/joenorton/comfyui-mcp-server/issues/18)).

`services/mcp/constraints.txt` now holds the SDK to `mcp>=1.8.0,<2`. 1.8.0 is
the first release with the `streamable-http` transport that upstream serves. The
image also imports `FastMCP` at build time, so the next drift fails the build
rather than the container. Nothing else in the release changed.

## 2.4.0 — 2026-09-21

### The release procedure, written down where it is followed

`VERSIONING.md` said `git tag && git push --tags` and stopped there, which
reads as though the Release object is incidental. It is not: the tag is the
trigger and **CI creates the Release**, attaching the attested wheel,
`SHA256SUMS` and `IMAGE-DIGESTS.txt`.

Creating the Release by hand with `gh release create` looks equivalent and
isn't. CI refuses to write into one that already exists — *"releases are
immutable"* — so the release job fails *after* every image has published. The
version ends up correct everywhere and the Release page empty. v2.1.0, v2.2.0
and v2.3.0 all have this shape; v2.0.0 and v1.4.0 show what it should look
like.

Those three are not backfilled on purpose. The wheel carries a provenance
attestation bound to the workflow run, so a hand-uploaded wheel would look
official and carry none. A missing asset is honest; an unattested one is not.

This release exists to cut one correctly, and to leave the reason in the file
someone reads before releasing.

## 2.3.0 — 2026-09-21

### `COMFYUI_VERSION` → v0.37.0, three releases in one step

The pin had been at v0.34.0 (2026-08-26) while upstream shipped v0.35.0,
v0.36.0 and v0.37.0. Nothing was wrong with the pin — it is deliberate and
reviewable by design — but nothing had reviewed it, so the release images were
five weeks behind what the nightly was proving daily.

**v0.37.0 is the first tagged release containing Qwen-Image-2.1.** Support
merged as `6bfaacc6` on 2026-09-19, four days after v0.36.0 was cut; the tag
is 8 commits past it. A consumer on a release image could not run that model
at all, which is why `*-nightly` existed — and this bump is what lets them
stop using it.

Everything else follows from the upstream jump and is theirs, not ours: the
0.34→0.37 asset-catalog migration rebuilds `comfyui.db` from scratch and keeps
the old one as `comfyui.db.bkp`. Expected on a ComfyUI upgrade of this size.

## 2.2.0 — 2026-09-20

### A nightly channel, because day-zero support never lives in a release

ComfyUI merges day-zero model support to master and tags a release up to a week
later. Qwen-Image-2.1 was open-weighted on 2026-09-20; its support landed in
`6bfaacc6` on 09-19, after v0.36.0 was cut on 09-15. Nothing here could build
it: the weekly rebuild resolved upstream's latest **release**, so a
release-following channel is structurally incapable of being day-zero.

**`*-nightly` is new** — built 02:00 UTC daily from upstream master, and never
moving `*-latest`. `workflow_dispatch` takes a `ref` (branch, tag or commit), so
a specific upstream commit can be built on demand. Every runtime is covered, as
the weekly was: cuda, cuda-arch, cpu, rocm, xpu.

**The weekly survives as a cache policy, not a workflow.** Sundays (and
`-f weekly=true`) bypass cache entirely, because the base image, apt and the
torch install sit BELOW the ComfyUI clone: a nightly busts the clone layer and
reuses everything under it, so a base-image fix would otherwise never land
however many nightlies ran. Same ref, same tags, same jobs — one channel.

One `context` job resolves the upstream commit and every build job consumes it,
so a run cannot build two runtimes from different commits. The weekly resolved
independently per job, which could.

**`COMFYUI_VERSION` now accepts a commit SHA.** The clone was
`git clone --depth 1 --branch "$COMFYUI_VERSION"`, and `--branch` cannot express
a commit — so the pin could not name the thing worth building. It is now an
explicit `fetch --depth 1` of the ref, still one round trip, and the nightly
passes a RESOLVED commit rather than a moving ref: any nightly can be rebuilt.

**The `cuda-v<upstream>` tag family is deleted.** It was a second identity for
an artifact that already has one, and the weekly cron was its author — so an
unreviewed job owned the release-image line, publishing `cuda-v0.36.0` while a
reviewed release published `cuda-2.0.0` containing v0.34.0. A consumer pinning
our version got an older ComfyUI than one pinning `latest`. What is inside is
stated once now, by `org.opencontainers.image.version`, which is equally true
for a commit.

Three publishing paths remain, each answering one question: `cuda-<sha8>` (a
build of our main, moves `cuda-latest`), `cuda-<semver>` (released), and
`cuda-nightly` (upstream master).

**Consumers pinning `cuda-v0.36.0` or similar must repin.** Existing tags are
not deleted, but no new ones appear. Pin `cuda-<semver>` for stability or
`cuda-nightly` to follow upstream — and pin by digest either way.

## 2.1.0 — 2026-09-20

### The skills reached Claude Code only, and said otherwise

`skills/` shipped as a plugin whose manifest Claude Code alone could read.
`skills/README.md` documented a pi install that has never worked, and Codex was
not addressed at all. Every failure was silent: the install succeeds, the skill
is absent, and only the harness the author develops on stays green.

Three keys, one per harness, all now present:

* `.claude-plugin/plugin.json` gains `"skills": "./skills"`. Claude Code infers
  `skills/` by convention and so was unaffected; Codex's manifest path does not
  infer it and installed **zero** skills.
* `package.json` is new, carrying `"pi": { "skills": ["./skills"] }`. pi reads no
  other manifest, so the documented `packages: ["git:github.com/…"]` entry cloned
  the repo and loaded nothing. The README also pinned `v0.1.0`, eight releases
  stale.
* `skills/README.md` now states which file each harness reads, what breaks
  without it, and the per-harness command that shows what a RUNNING harness
  actually loaded — the tree looked correct throughout.

Still outstanding, in `pixeloven/marketplace`: this repo has no catalogue entry,
so `codex plugin add comfyui-docker@pixeloven` cannot resolve until one is added.
That is a change to a different repository.

## 2.0.1 — 2026-09-20

### `resolve` trusted a git sha1 as a sha256 for every non-LFS file

HuggingFace serves LFS objects and plain git objects from the same URL, and
only the LFS ones carry a content sha256 in `x-linked-etag`. A file under the
LFS threshold — `config.json`, `tokenizer.json` — answers with the **git blob
sha1** instead: `sha1(b"blob <len>\\0" + content)`, 40 hex wide, and not a hash
of the content alone. `_hf` recorded it under `type: SHA256` regardless.

Nothing caught it because the consumer store was pure-LFS. It surfaced the
first time a manifest needed a model DIRECTORY rather than a single weights
file (a Florence-2 captioning model: safetensors + tokenizer + config). The
lock resolved clean, `check` passed, and then `fetch` refused four of six
files with `sha256 mismatch` — correctly, since it hashes what it downloaded
and a sha1 cannot match.

The failure shape is worse than a plain error: the weights verify and land, so
the directory EXISTS but is incomplete. Custom nodes that guard their own
download with `if not os.path.exists(model_path)` then skip it and fail at load
on the missing tokenizer.

`resolve` now checks the etag's width and falls back to downloading and hashing
when it is not 64 hex. The LFS path stays a single HEAD — re-hashing those would
turn a resolve into a full fetch of the store — and the files this fires for are
the small ones by definition.

Locks resolved before this contain sha1s for their non-LFS entries and must be
re-resolved; `fetch` was already refusing them, so nothing was materialised
against a wrong hash.

## 2.0.0 — 2026-09-14

**MAJOR: `check` now validates the manifest format, and a manifest that passed
on 1.4.0 can fail on 2.0.0.** `VERSIONING.md` is explicit — *"a break in the
lock or manifest format … is not a patch however small the diff looks"* — and
this is exactly that. A real consumer's manifest goes from passing to 43 errors
until three key names gain an `x-` prefix.

Closes #67.

### `check` owns the definition of a valid manifest

The schemas ship as **package data**. Until now a consumer wanting schema
validation ran `check-jsonschema` against a path inside a checkout of this repo
— the only reason some of them kept one. **The root `schemas/` directory is
deleted**: two files with the same `$id` and CI validating the stale one is
worse than no schema check.

Format is validated **before** consistency. A manifest with `instal:` for
`install:` is perfectly consistent with a lock that therefore contains nothing,
so checking agreement first reports a confusing symptom of a plain typo.

### Extensions are named, not allowed

`additionalProperties: false` is what makes a typo an error, so it stays, and
`^x-` keys are permitted alongside it at file and group level — the convention
OpenAPI settled on. **This is the breaking part**: a consumer carrying its own
keys must prefix them.

### `capabilities:` is part of the format

It was absent from the schema entirely, so it passed *by accident* — the top
level simply wasn't closed. Both are fixed. Two offline semantic checks come
with it:

- a capability naming a profile that doesn't exist
- a capability requiring a `type:` **none of its own profiles resolve**

The second is scoped per-capability, not manifest-wide. Collecting every type
in the manifest makes the check nearly vacuous: a capability whose profiles
resolve only upscalers would satisfy `requires: [diffusion_models]` because
some unrelated lineage declares one.

### `check --parent`

Asserts a derived lock is a **verbatim subset** of its source. `--from-lock`
selects rather than re-resolves, so no hash in a profile lock can legitimately
differ. Resolving each profile independently lets locks made minutes apart pin
different upstream commits, and nothing downstream notices — each lock is
internally consistent and each passes `check`.

Subset is tested by **membership**, not by keying on the `model` filename: lock
identity is the install path, and the same basename legitimately appears more
than once. One real lock already carries two `qwen_3_4b.safetensors` from
different repos — one file shared by two lineages, declared by each so either
resolves alone.

### `fetch` validates its lock too

Asked for in #67 and sharper there than in `check`: **fetch writes.** A
malformed lock puts files in the wrong place, or none at all, after the network
has already been used.

### Machine output carries the reason

`Out.problem` is a deliberate no-op under `--output json`, so the new failure
paths initially exited 1 with **zero bytes on either stream** — a machine
consumer got a failure with no reason attached. Every failure path now emits
the same `{"ok": false, "problems": [...]}` shape as the success path.

**PyPI is deliberately absent.** #67 proposed it; the issue's own resolution
says skip it, and `VERSIONING.md` codifies the release-attached wheel.

### The verification core is tested offline, and three dead CLIs are gone

Almost every `fetch` test was `@pytest.mark.network`, which CI deselects — so
the code deciding whether bytes on disk are trustworthy ran in one executed
test. Deleting the present-file hash comparison, the `.fetch-tmp` cleanup on
mismatch, or the extra-install-paths copy each left the suite green. 15 offline
tests via respx now kill all three, and `check --profile` — previously untested
outright — is covered. Offline coverage 72% → 80%; `fetch.py` 43% → 85%.

Also removes `fetch.main`, `check.main` and resolve's leftover imports: three
orphaned `comfy-fetch` / `comfy-check-lock` / `comfy-resolve` argparse CLIs with
no `console_scripts` entry and no caller, left behind by the Typer port. **No
user-visible change** — nothing could invoke them — but they were a second,
divergent definition of the same interface, `check`'s copy using different exit
codes. That is the shape every recent defect here has had.

## 1.4.0 — 2026-09-14

**`comfyfetch facts --headers`** — supply safetensors headers as JSON instead of
reading them from a store.

`facts` needs two inputs that are not always on the same machine. In a
Kubernetes deployment the model store lives inside the cluster, on a
node-pinned volume, while the lineage sources live in a git checkout outside
it — so `--store` alone makes the verb unusable in exactly the deployment it
was written for. Extracting headers is a separable step, so it is now separate:

```sh
# inside the cluster
kubectl exec <pod> -- python3 -c '...' > headers.json
# outside it, where the sources are
comfyfetch facts models/ comfy-lock.yaml --headers headers.json
```

`--store` and `--headers` are mutually exclusive: two sources for one input is
a wrong request (exit 2), not something to merge.

## 1.3.0 — 2026-09-14

**`comfyfetch facts`** — measure what a model IS, versus what its filename
claims.

Reads the trainer's metadata out of safetensors headers and resolves each file
against Civitai **by content hash**, writing a `<lineage>.facts.yaml` sidecar.
Auditing a real 124-file SDXL store this way found 2 mislabelled models, 3 LoRAs
trained on bases that were not present, and 33 trigger words that existed
nowhere — without which a style LoRA loads, consumes VRAM and does nothing.

Three sources, in decreasing authority: `ss_sd_model_hash` / `ss_sd_model_name`
from the file itself → Civitai by content hash → Civitai by declared source id.

### Two traps the code exists to avoid

- **Never use `ss_base_model_version` for lineage.** It reports
  `sdxl_base_v1-0` for essentially every SDXL file — the *architecture*, not
  the finetune. Taking it for lineage mislabels a whole store at once.
- **Never infer lineage from the install path.** It records where a file was
  *filed* — wrong for 2 of 48 LoRAs and 1 of 16 checkpoints. `describe()` takes
  no path parameter, so the mistake cannot be made here, and a test asserts
  that signature.

### A correction to earlier documentation

Previous notes on this tooling claimed Civitai needs a bearer token **and** a
non-default User-Agent. It does **not** need the token for public by-hash
lookups: the 403 is a block on the literal `Python-urllib/3.12`, and every
other UA tried — including a lowercased one — returns 200 without credentials.
That block silently failed 38 of 106 lookups and was misdiagnosed as auth,
which is worse than leaving it unexplained. `--token` is optional. Whether a
token unlocks gated versions is **untested and not asserted**.

### Reproducibility is a property of the interface

`generated` and the attribution line are **parameters**, not ambient facts, so
a sidecar can be diffed against its committed form. A generator rename must not
read as the facts having changed.

### Verification

Byte-identical against a committed sidecar from a real store, with every
network response replayed from a recorded corpus — so the suite is offline and
deterministic, which matters here because the sidecars carry live Civitai
fields that uploaders edit.

The diff also **surfaced a real gap**: the original took a hand-built
name→sha map, and whatever was omitted from it was silently never looked up.
One file was. Taking the hashes from the lock instead is why the interface is
`(sources, lock)`, and a test asserts the file that was missed is now found.

## 1.2.0 — 2026-09-13

**httpx replaces the hand-rolled urllib transport**, and the test dependencies
this project needs are now declared.

`comfyfetch/http.py` was 86 lines of `urllib` whose centrepiece was a custom
redirect handler. That handler existed to strip `Authorization` on a cross-host
redirect — because HuggingFace answers `/resolve/` with a 302 to `*.cdn.hf.co`
and urllib forwards every header across a redirect, including that one.
**httpx does it natively.**

A third problem stops being possible. Civitai returns **403 for the literal
`Python-urllib/3.12`** and 200 for every other User-Agent tried, including a
lowercased one. That block silently failed 38 of 106 lookups in a downstream
audit and was misdiagnosed as "needs a bearer token" — a wrong explanation of
a real symptom, which is worse than none. A client that does not send the
stdlib default cannot reproduce it. Verified live after the change: Civitai
returns 200 with no token and an explicit `comfyfetch/<version>` UA.

**Both behaviours this module is correct about are now tested**, and neither
was before — `respx` makes them testable without a network:

- `Authorization` is stripped on a cross-origin redirect and **survives** a
  same-origin one
- `head_headers` reads the **first hop only**. `x-linked-etag` is the file's
  sha256 there and nowhere else; following the redirect returns the CDN's Xet
  content-address, a different and equally plausible-looking 64-hex value.
  Four wrong hashes were produced that way before someone downloaded a file
  and hashed it.

### Also

- `pytest` and `respx` are declared in a `dev` dependency group. A project with
  73 tests required `uv run --with pytest --with respx` to run them, which is a
  step that gets typed wrong or skipped. **`uv run pytest` now works.**
- Two `except urllib.error.HTTPError` sites became `httpx.HTTPStatusError`.
  This was caught by the existing suite, not by reading — a resolve failure
  must be *reported* per-source, and an unhandled exception aborts the run
  instead.

No behaviour change for callers: `request()` still returns a streaming,
context-managed file-like object supporting `read(n)` and `json.load()`.
Verified byte-identical `build` output against a real 68-group manifest, and
the HF first-hop etag against the live endpoint.

## 1.1.1 — 2026-09-13

**A group and a profile may no longer share a name.**

comfyfetch resolves both out of one namespace, and `expand()` tests
`member in known` before `member in profiles` — so the group always wins. A
profile named after a group silently resolved the **group**, at every level,
and the resulting lock was self-consistent, correctly hashed and passed
`check`, because all of `resolve`, `--from-lock` and `check --profile` go
through that same function.

Observed downstream before this refusal existed: one profile resolved **2 files
instead of 13**, another **3 instead of 15**. No error either time; the only
symptom was a file count nobody was watching.

Refused in three places, because one is not enough:

- `expand()` — covers `resolve --profile`, `--from-lock` and `check --profile`
- `validate_all()` — as a **pre-check**, so one defect is reported once rather
  than once per profile
- `build.render()` — load-bearing rather than belt-and-braces: **`resolve`
  without `--profile` never calls `expand()` at all**, so refusing at assembly
  time is what stops a colliding manifest reaching disk

**This tightens previously-accepted input**, which `VERSIONING.md` would
normally make a MAJOR change. Shipped as a patch deliberately: the schema never
defined what a name meaning two things should do, so no documented behaviour
changes — only silently-wrong behaviour becomes an error. Exit code **2**, the
existing "the request itself was wrong" code.

Verified against a real 68-group manifest: byte-identical output, and 0
collisions there, in this repo's own manifest, and across all test fixtures.

## 1.1.0 — 2026-09-13

**`comfyfetch build`** — assemble a manifest from per-lineage source files.

A single `comfy.yaml` does not scale. Past a few hundred lines every model
family conflicts with every other on edit, and there is no way to ship one
family without the rest. `build` assembles it from one file per lineage under a
directory the caller lays out:

```sh
comfyfetch build models/ -O comfy.yaml
comfyfetch build models/ -O comfy.yaml --check     # offline; what CI runs
```

`--check` exists because the manifest stays **committed**: a build step between
`git clone` and `comfyfetch check` is a step that gets skipped, and a stale
manifest resolves the *wrong models* while every other gate stays green.

Each source file may carry a **`summary:`** — the judgement a reader needs and
a file list cannot express ("two generations, NOT interchangeable"; "we ship
fp8 where the tutorial ships bf16, measured, identical adherence at half the
size"). `build` re-attaches it above that lineage's first group so it reaches
the artifact rather than staying in a file nobody reads. That is the whole
reason `build` is not `cat`.

Extracted from a real store of 68 groups across 13 lineages and verified
against it: the verb reproduces that store's committed manifest
byte-identically. Duplicate group names are fatal rather than last-wins — two
lineages declaring one group is an editing accident, and silently keeping one
drops models nobody asked to drop.

The extraction found a defect in the original implementation: the summary match
looked for `- name: ` at column 0 while the yamllint indent fix emits
`  - name: `, so it fired on nothing and every summary was dropped, silently,
with no error in either direction.

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
