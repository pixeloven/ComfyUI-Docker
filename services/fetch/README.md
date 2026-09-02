# fetch — manifest, lock, and verified materialisation

Three small tools and an image, following npm's shape:

| | | |
|---|---|---|
| **`comfy.yaml`** | manifest | Hand-authored. Declares *intent*. |
| **`comfy-resolve`** | resolver | Manifest → lock. Talks to the network. Run when you change the manifest or want to move a ref. |
| **`comfy-lock.yaml`** | lock | **Generated.** Exact commits, exact URLs, exact hashes. |
| **`comfy-fetch`** | fetcher | Lock → disk, verifying every file. Never reads the manifest. |
| **`comfy-check-lock`** | gate | Manifest and lock still agree. Offline. |

Python 3.13 on Alpine, PyYAML the only dependency, ~88 MB image.

It was shell, and the trade is deliberate. The shell version accumulated seven
distinct classes of silent bug — the worst being a `yq` whose escape handling
differs between *patch* releases, which once made the record parser match
nothing, process zero files and exit 0. The property given up, "no language
runtime", costs 39 MB and was always weak: a consumer runs an image, they do not
install an interpreter.

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
# comfy-lock.yaml — comfy-resolve writes this
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
comfy-resolve comfy.yaml                                       > locks/everything.yaml
comfy-resolve comfy.yaml --profile image --from-lock locks/everything.yaml > locks/image.yaml
comfy-resolve comfy.yaml --profile video --from-lock locks/everything.yaml > locks/video.yaml

comfy-fetch locks/image.yaml /workspace --apply
comfy-fetch locks/video.yaml /workspace --apply   # shared files already correct, skipped
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

`comfy-check-lock` validates profiles offline: every member must be a known model
or another profile, and expansion must terminate. Cycle detection is by bounded
expansion rather than a self-reference check, because `a → b → a` is the same
defect one step further out.

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

## Usage

```sh
comfy-resolve comfy.yaml > /tmp/m.yaml            # then splice into comfy-lock.yaml
yq -i '.models = load("/tmp/m.yaml").models' comfy-lock.yaml

comfy-fetch comfy-lock.yaml /workspace       # dry run
comfy-fetch comfy-lock.yaml /workspace --apply

comfy-check-lock comfy.yaml comfy-lock.yaml       # offline; what CI runs
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
would otherwise be unknowable offline — which `comfy-check-lock` depends on.

## Why CI does not re-resolve

`comfy-check-lock` compares manifest against lock **offline** and never re-resolves.
A moving `revision:` is *supposed* to yield a new commit once upstream advances —
so a re-resolve gate would fail for the one reason that is not a mistake, and
would need network access to do it. Hash changes arrive through a deliberate
`comfy-resolve` run and are reviewed like any other diff.

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
  has none. `comfy-resolve` falls back to downloading and hashing, which is correct
  but slow; state `sha256:` in the manifest to skip it.
- **Bind mounts and DinD.** Where CI's filesystem is not the Docker host's,
  `-v "$(mktemp -d):/w"` silently mounts an empty directory. `verify.sh` is
  piped in over stdin for exactly that reason.
