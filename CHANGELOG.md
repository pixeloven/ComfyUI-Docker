# Changelog

Everything this repo publishes, under one version: the ComfyUI images
(`complete`, `core`, `runtime`), the `mcp` image, the `comfyfetch` image **and
wheel**, and the skills plugin. Released as `vX.Y.Z`; the version lives in
`VERSION`, and every manifest that states it must agree.

This is **our packaging version**, not what is inside the image. `COMFYUI_VERSION`
is pinned in `docker-bake.hcl`, published alongside, and moves independently —
see `VERSIONING.md`.

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
