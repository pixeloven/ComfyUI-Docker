# fetch — manifest, lock, and verified materialisation

Three small tools and an image, following npm's shape:

| | | |
|---|---|---|
| **`comfy.yaml`** | manifest | Hand-authored. Declares *intent*. |
| **`comfyctl fetch resolve`** | resolver | Manifest → lock. Talks to the network. Run when you change the manifest or want to move a ref. |
| **`comfy-lock.yaml`** | lock | **Generated.** Exact commits, exact URLs, exact hashes. |
| **`comfyctl fetch fetch`** | fetcher | Lock → disk, verifying every file. Never reads the manifest. |
| **`comfyctl fetch check`** | gate | Manifest and lock still agree. Offline. |

This directory is the `comfyfetch` **library**. Its command is `comfyctl fetch`,
which mounts comfyfetch's own Typer app as a group
([services/comfyctl](../comfyctl/README.md)). Before 4.0.0 it was a separate
`comfyfetch` command, with the same verbs, flags, output and exit codes.

Python 3.13 on Alpine — PyYAML and Typer — as a ~102 MB image **or** a CLI you
install directly:

```sh
uvx --from 'git+https://github.com/pixeloven/ComfyUI-Docker@v4.0.0#subdirectory=services/comfyctl' comfyctl fetch --help
```

Pin the tag, as above. An unpinned line follows `main`, and that's how 3.x users
of the old `comfyfetch` line broke when 4.0.0 renamed the command.

**Never let an installer resolve `comfyfetch` from a package index.** Neither
`comfyfetch` nor `comfyctl` is registered on PyPI, so anyone could publish a
package under either name. The `uvx` line above takes comfyfetch from the same
git commit. From a release, pass the comfyfetch wheel explicitly with
`--with <comfyfetch wheel url>`, as [services/comfyctl](../comfyctl/README.md#install)
shows. `pip install` of the git subdirectory, or a bare `comfyctl` wheel with no
`--with`, looks comfyfetch up on PyPI instead.

The image is for automated deployment; the CLI is for managing your own
configuration, and for agents. They are the same code and the same behaviour.

Typer, matching comfy-cli and Harmony's `hmy` rather than inventing a third
convention. Deliberately **not** named `comfy`/`comfy-cli`/`comfycli` — comfy-cli
owns those.

### Why not shell

It was, and the trade is deliberate. The shell version accumulated seven
distinct classes of silent bug — the worst being a `yq` whose escape handling
differs between *patch* releases, which once made the record parser match
nothing, process zero files and exit 0. The property given up, "no language
runtime", costs 39 MB and was always weak: a consumer runs an image, they do not
install an interpreter. The finished image is 102 MB against 48.5 MB.

### Output and exit codes

`--output auto` colours at a terminal and goes plain when piped, which is every
CI job and every container. `--output json` gives automation and agents stable
keys. Human output goes to **stderr**; stdout carries the artifact, so
`comfyctl fetch resolve … > lock.yaml` stays correct.

| exit | meaning |
|---|---|
| `0` | did what was asked |
| `1` | a real failure — a source did not resolve, a hash did not match, a lock and its manifest disagree |
| `2` | the request was wrong — missing file, unknown profile, incompatible flags |

## Why a lock at all

A lock file — `package-lock.json`, `Cargo.lock`, `uv.lock`, `go.sum` — is
generated rather than authored, records the *resolved* result of a separately
declared intent, and exists for reproducibility plus integrity. `package.json`
says `react ^18`; `package-lock.json` says `18.3.1` with a `sha512`.

Here, `revision: main` is the `^18`. The lock pins it to a commit and records
the sha256 of the bytes that commit serves:

```yaml
# comfy.yaml — you edit this
      - source: hf:Comfy-Org/Qwen-Image_ComfyUI
        file: split_files/vae/qwen_image_vae.safetensors
        install: models/vae/
        type: vae
```

```yaml
# comfy-lock.yaml — comfyctl fetch resolve writes this
  - model: qwen_image_vae.safetensors
    url: https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/7beb7b64…/split_files/vae/qwen_image_vae.safetensors
    paths:
      - path: models/vae/qwen_image_vae.safetensors
    hashes:
      - hash: a70580f0213e67967ee9c95f05bb400e8fb08307e017a924bf3441223e023d1f
        type: SHA256
    type: vae
```

The lock's `models[]` entries are **byte-for-byte** comfy-cli's documented
`comfy-lock.yaml` shape — `model`, `url`, `paths`, `hashes`, `type` — with no
additions, so anything that learns to read a comfy-lock reads ours unmodified. **The only extension anywhere is the top-level `auth` map**, which upstream has
no equivalent for and which never appears inside a model entry.

Verification is the point. **A wrong-but-plausible model file is worse than a
missing one** — a missing file fails loudly at load; a wrong one renders subtly
wrong images forever, with no error anywhere. An entry with no `SHA256` is
refused rather than fetched unverified.

## Profiles

Named sets of capabilities, resolved into separate locks:

```yaml
models:
  - name: qwen-image     …
  - name: real-esrgan    …     # defined ONCE, shared

profiles:
  image:      [qwen-image, real-esrgan]
  image-fast: [qwen-image, qwen-image-lightning, real-esrgan]
  everything: [image-fast]     # a member may be another profile
```

```sh
# Resolve the full set ONCE, then derive each profile from it.
comfyctl fetch resolve comfy.yaml                                       > locks/everything.yaml
comfyctl fetch resolve comfy.yaml --profile image --from-lock locks/everything.yaml > locks/image.yaml
comfyctl fetch resolve comfy.yaml --profile video --from-lock locks/everything.yaml > locks/video.yaml

comfyctl fetch fetch locks/image.yaml /workspace --apply
comfyctl fetch fetch locks/video.yaml /workspace --apply   # shared files already correct, skipped
```

`--from-lock` selects from an existing lock instead of resolving. Producing N
profile locks otherwise means N network passes over heavily overlapping files —
and, worse, locks resolved minutes apart can legitimately pin *different*
commits if a moving `revision:` advanced between runs. Deriving them from one
parent makes every profile pin identical commits by construction, and each
derived lock is a **strict subset** of that parent, copied verbatim.

If the parent does not hold a file the profile selects, it is stale: the command
says so and writes nothing, rather than emitting a lock that is quietly short.

Profiles compose by **set union**, not inheritance — no resolution order, no
overrides, no diamonds. A model shared between two profiles is defined once and
appears in both locks; materialising both installs it once, because the fetch is
content-addressed and the second pass sees a matching hash.

`comfyctl fetch check` validates profiles offline: every member must be a known model
or another profile, and expansion must terminate. Cycle detection is by bounded
expansion rather than a self-reference check, because `a → b → a` is the same
defect one step further out.

## Versions

`comfyfetch` and `comfyctl` share the repository's version — one number covers
the images, the wheels and the skills plugin. It lives in `VERSION`, and both
`pyproject.toml` files must state the same value; CI checks that on every push,
and **refuses a tag that disagrees**, so a `v1.2.0` tag cannot ship `1.1.0` code.

So this version does not say "what changed in the CLI" — `CHANGELOG.md` does.
That trade buys one release page describing the whole repo instead of two
describing halves of it; see `VERSIONING.md`.

A release publishes `fetch:1.2.0` and `fetch:1.2` alongside the commit-sha and
`latest` tags an ordinary push produces, plus the `comfyctl` and `comfyfetch`
wheels as release assets. Install them as a pair, passing the comfyfetch wheel
with `--with` so it never comes from an index; see
[services/comfyctl](../comfyctl/README.md#install).

**Pin by digest** — the semver tags say whether a digest change was a patch or a
break; they are not themselves a safe pin, because a tag can move.

`comfyctl fetch --version` reports what an installed copy is. See
[CHANGELOG.md](../../CHANGELOG.md).

## Validating before a deployment starts

The image carries `check`, so a deployment can gate itself on its own mounted
config rather than trusting CI:

```yaml
initContainers:
  - name: check
    image: ghcr.io/pixeloven/comfyui/fetch@sha256:...
    command: ["comfyctl", "fetch"]
    args: ["check", "/config/comfy.yaml", "/config/locks/common.yaml", "--profile", "common"]
```

A non-zero exit blocks the pod. This catches what CI cannot: CI validates the
*repository*, this validates the *deployment* — the actual mounted files, at the
moment they are about to be used. A repo can be green while a cluster runs a
stale ConfigMap.

## Trying it

```sh
cd examples/core-gpu
cp .env.example .env
docker compose --profile models up
```

Materialises the `preview` lock — 9.5 MB of TAESD decoders, ComfyUI's live
preview autoencoders — into `data/models/vae_approx/`, verifying each file, then
starts ComfyUI. A plain `docker compose up` skips it entirely. Point
`COMFY_LOCK` at `../../comfy-lock.yaml` for the full set.

`data/models/.gitkeep` is shipped deliberately: **Docker creates a missing
bind-mount source directory as root**, and this image runs non-root by design,
so without it the first run fails with `destination not writable`. The comfyui
service survives the same situation only because its entrypoint starts as root
and drops privileges via gosu.

## Authoring a manifest from per-lineage sources

A single `comfy.yaml` does not scale. Past a few hundred lines every model
family conflicts with every other on edit, and there is no way to ship one
family without the rest. `build` assembles the manifest from **one file per
lineage**:

```
models/
  _meta.yaml          name, description, auth
  profiles.yaml       copied through
  capabilities.yaml   copied through
  shared/flux.yaml    family + lineage + summary + groups
  shared/qwen.yaml
  custom/sdxl.yaml
```

```sh
comfyctl fetch build models/ -O comfy.yaml
comfyctl fetch build models/ -O comfy.yaml --check    # offline; what CI runs
```

Each source file may carry a **`summary:`** — the judgement a reader needs and
a file list cannot express ("two generations, NOT interchangeable"; "we ship
fp8 where the tutorial ships bf16, measured, identical adherence at half the
size"). `build` re-attaches it as a comment above that lineage's first group,
so it survives into the artifact rather than staying in a file nobody reads.
That is the whole reason `build` is not `cat`.

The generated manifest stays **committed**. A build step between `git clone`
and `comfyctl fetch check` is a step that gets skipped, and `--check` catches the
staleness that results — a stale manifest resolves the *wrong models* while
every other gate stays green.

Directory layout is yours. `build` walks the tree and does not care how it is
split; a `shared/` vs `custom/` seam (reproducible-from-public-docs vs personal
taste) is a convention worth having precisely because it is a directory
boundary, so separating the halves later is `git mv` rather than a re-sort.

## Usage

```sh
comfyctl fetch build models/ -O comfy.yaml                 # offline; manifest from sources

comfyctl fetch resolve comfy.yaml > /tmp/m.yaml            # then splice into comfy-lock.yaml
yq -i '.models = load("/tmp/m.yaml").models' comfy-lock.yaml

comfyctl fetch fetch comfy-lock.yaml /workspace       # dry run
comfyctl fetch fetch comfy-lock.yaml /workspace --apply

comfyctl fetch check comfy.yaml comfy-lock.yaml       # offline; what CI runs
comfyctl fetch build models/ -O comfy.yaml --check     # offline; what CI runs
```

Paths in the lock begin `models/`, so the fetcher's second argument is the
**ComfyUI root**, not the models directory.

### Pinning it

Every push to `main` publishes the image and prints its digest to the workflow
run summary:

```
ghcr.io/pixeloven/comfyui/fetch:<commit-sha>
ghcr.io/pixeloven/comfyui/fetch:latest
```

**Pin by digest, not by tag.** `latest` moves, and a fetcher that changes under a
deployment is the opposite of what a lock is for:

```
ghcr.io/pixeloven/comfyui/fetch@sha256:...
```

Docker:

```sh
docker run --rm -v comfyui:/workspace -v "$PWD/comfy-lock.yaml:/lock.yaml:ro" \
  ghcr.io/pixeloven/comfyui/fetch:latest /lock.yaml /workspace --apply
```

The entrypoint is `comfyctl fetch fetch`, so appended arguments go to the
`fetch` verb. Any other verb replaces the entrypoint:

```sh
docker run --rm --entrypoint comfyctl -v "$PWD:/w:ro" \
  ghcr.io/pixeloven/comfyui/fetch:latest fetch check /w/comfy.yaml /w/comfy-lock.yaml
```

## Carrying your own metadata

File and group entries reject unknown keys — `instal:` for `install:` installs
nothing and reports success, so that check is worth keeping. Extensions are
therefore **named** rather than allowed: any key starting `x-` is yours.

```yaml
models:
  - name: sdxl-illustrious
    x-lineage: illustrious            # group level
    files:
      - source: civitai:1234
        install: models/loras/
        as: my-style-lora.safetensors  # civitai URLs carry no filename
        x-triggers: [score_9]          # file level
        x-generation: "2511"
```

comfyfetch ignores their content entirely. They exist so the file you already
maintain can carry what your deployment needs.

## Validating

```sh
comfyctl fetch check comfy.yaml comfy-lock.yaml
comfyctl fetch check comfy.yaml locks/sdxl.yaml --profile sdxl --parent comfy-lock.yaml
```

The schemas ship **with the package**, so this needs no checkout of this repo.
Format is checked before consistency: a typo'd key is perfectly consistent with
a lock that therefore contains nothing, and reporting the disagreement first
describes a symptom rather than the cause.

`--parent` asserts a derived lock is a **verbatim subset** of the lock it came
from. `--from-lock` selects rather than re-resolves, so a difference means
something was re-resolved — and that is how two locks generated minutes apart
come to pin different upstream commits with nothing noticing.

## Capabilities

A capability names the profiles that provide it and the model `type:` values a
graph needs to actually render:

```yaml
capabilities:
  image-generation-flux2:
    profiles: [flux2]
    requires: [diffusion_models, text_encoders, vae]
```

`profiles` is plural and load-bearing: an add-on profile resolves no checkpoint
by design, so the contract is checked against the **union** of the profiles a
capability names. `check` verifies those profiles exist and that each required
type is resolved by one of them — a capability requiring `vae` that resolves
zero is a graph that loads and cannot render.

## Credentials

A host-keyed map, declared once in the manifest and copied through to the lock:

```yaml
auth:
  civitai.com: ${CIVITAI_TOKEN}
  huggingface.co: ${HF_TOKEN}
  github.com: ${GITHUB_TOKEN}
```

The fetcher resolves a credential by the URL's **host**, so **no model entry
carries an auth field** — which is why `models[]` in the lock stays comfy-cli's
documented shape.

Values must be `${ENV_VAR}` references. **The schema rejects a literal**, so a
token cannot be committed by accident.

A host listed here whose variable is *unset* does not block anything — most
HuggingFace files are public, and refusing them because `HF_TOKEN` happens to be
unset would be wrong. The missing variable is recorded and **named in the error
if the fetch then fails**, which is the case a bare `sha256 mismatch` would
otherwise misattribute: an unauthenticated Civitai request returns an HTML error
page with HTTP 200.

Resolution needs no credentials at all — HuggingFace returns hashes in headers,
Civitai's `model-versions` endpoint is public, and GitHub's release API is too
(a `GITHUB_TOKEN` only raises the rate limit). Tokens are needed to *fetch*.

## Sources

| form | resolved from |
|---|---|
| `hf:<owner>/<repo>` + `file:` | `x-repo-commit`, `x-linked-etag`, `x-linked-size` headers |
| `gh:<owner>/<repo>@<tag>` + `file:` | the release API's asset `digest`, `size` |
| `civitai:<modelVersionId>` | `files[0].hashes.SHA256`, `downloadUrl`, `sizeKB` |
| `https://…` | nothing — **you must supply `sha256:`** |

`civitai:` sources require `as:`, because the filename comes from the API and
would otherwise be unknowable offline — which `comfyctl fetch check` depends on.

## Why CI does not re-resolve

`comfyctl fetch check` compares manifest against lock **offline** and never re-resolves.
A moving `revision:` is *supposed* to yield a new commit once upstream advances —
so a re-resolve gate would fail for the one reason that is not a mistake, and
would need network access to do it. Hash changes arrive through a deliberate
`comfyctl fetch resolve` run and are reviewed like any other diff.

## Things that will bite you

- **`urllib` forwards `Authorization` across redirects**, stripping only
  content-length and content-type. curl does not. HuggingFace answers
  `/resolve/` with a 302 to `*.cdn.hf.co` — a different host — so a naive port
  sends the account token to the CDN on every gated download. Credentials are
  stripped when scheme, host *or port* changes; host alone is not enough.
- **`x-linked-etag` is the sha256 — but only on the first hop.** Following the
  redirect gives the CDN's Xet content-address instead: a different, equally
  plausible-looking value. Resolve with `curl -sI`, never `-sIL`.
- **GitHub only computes asset digests for newer uploads.** Much of the ComfyUI
  ecosystem's models sit on releases from 2021 — `xinntao/Real-ESRGAN@v0.1.0`
  has none. `comfyctl fetch resolve` falls back to downloading and hashing, which is correct
  but slow; state `sha256:` in the manifest to skip it.
- **Bind mounts and DinD.** Where CI's filesystem is not the Docker host's,
  `-v "$(mktemp -d):/w"` silently mounts an empty directory. `verify.sh` is
  piped in over stdin for exactly that reason.
