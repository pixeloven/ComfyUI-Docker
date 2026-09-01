# fetch — manifest, lock, and verified materialisation

Three small shell tools and an image, following npm's shape:

| | | |
|---|---|---|
| **`comfy.yaml`** | manifest | Hand-authored. Declares *intent*. |
| **`resolve.sh`** | resolver | Manifest → lock. Talks to the network. Run when you change the manifest or want to move a ref. |
| **`comfy-lock.yaml`** | lock | **Generated.** Exact commits, exact URLs, exact hashes. |
| **`fetch-lock.sh`** | fetcher | Lock → disk, verifying every file. Never reads the manifest. |
| **`check-lock.sh`** | gate | Manifest and lock still agree. Offline. |

Dependencies: `curl`, `sha256sum`, `yq`. No language runtime, ~48 MB image.

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
# comfy-lock.yaml — resolve.sh writes this
  - model: qwen_image_vae.safetensors
    url: https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/7beb7b64…/split_files/vae/qwen_image_vae.safetensors
    paths:
      - path: models/vae/qwen_image_vae.safetensors
    hashes:
      - hash: a70580f0213e67967ee9c95f05bb400e8fb08307e017a924bf3441223e023d1f
        type: SHA256
    size_bytes: 253806246
    type: vae
```

The lock is comfy-cli's documented `comfy-lock.yaml` shape, including its
`hashes: [{hash, type}]` block. **One field is an extension: `auth`**, naming
which credential a source needs. It is the only thing the upstream format cannot
express that a *verifying* fetcher requires.

Verification is the point. **A wrong-but-plausible model file is worse than a
missing one** — a missing file fails loudly at load; a wrong one renders subtly
wrong images forever, with no error anywhere. An entry with no `SHA256` is
refused rather than fetched unverified.

## Usage

```sh
resolve.sh comfy.yaml > /tmp/m.yaml            # then splice into comfy-lock.yaml
yq -i '.models = load("/tmp/m.yaml").models' comfy-lock.yaml

fetch-lock.sh comfy-lock.yaml /workspace       # dry run
fetch-lock.sh comfy-lock.yaml /workspace --apply

check-lock.sh comfy.yaml comfy-lock.yaml       # offline; what CI runs
```

Paths in the lock begin `models/`, so the fetcher's second argument is the
**ComfyUI root**, not the models directory.

Docker:

```sh
docker run --rm -v comfyui:/workspace -v "$PWD/comfy-lock.yaml:/lock.yaml:ro" \
  ghcr.io/pixeloven/comfyui/fetch:latest /lock.yaml /workspace --apply
```

Credentials come from the environment — `CIVITAI_TOKEN`, `HF_TOKEN` — never from
either file. A source needing a token you do not have is **not attempted**,
because an unauthenticated Civitai request returns an HTML error page with HTTP
200, which would be written to disk and then fail the hash check with a message
naming the wrong cause.

Resolution needs no credentials at all: HuggingFace returns hashes in headers and
Civitai's `model-versions` endpoint is public. Tokens are needed to *fetch*.

## Why CI does not re-resolve

`check-lock.sh` compares manifest against lock **offline** and never re-resolves.
A moving `revision:` is *supposed* to yield a new commit once upstream advances —
so a re-resolve gate would fail for the one reason that is not a mistake, and
would need network access to do it. Hash changes arrive through a deliberate
`resolve.sh` run and are reviewed like any other diff.

## Things that will bite you

- **`yq` version matters.** 4.47 emits `"\t"` inside an expression literally;
  4.53 interprets it as a tab. Every record format here is therefore
  escape-free — one field per line — and each script asserts that the number of
  records it read equals the number the file declares. Without that, a parser
  matching nothing reports `0 failed` and exits 0.
- **`$(...)` strips trailing newlines**, so a record whose last fields are empty
  loses them and `read` desynchronises or hits EOF — under `set -e`, silently,
  mid-loop. Absent values are emitted as `-`, never as an empty line. A sentinel
  line appended *after* the substitution does not help; the stripping happens
  first.
- **`[ cond ] && cmd` as the last statement of a loop body** makes the body
  return non-zero when the test fails, and `set -e` then kills the loop. Use
  `if`.
- **`x-linked-etag` is the sha256 — but only on the first hop.** Following the
  redirect gives the CDN's Xet content-address instead: a different, equally
  plausible-looking value. Resolve with `curl -sI`, never `-sIL`.
- **Bind mounts and DinD.** Where CI's filesystem is not the Docker host's,
  `-v "$(mktemp -d):/w"` silently mounts an empty directory. `verify.sh` is
  piped in over stdin for exactly that reason.
