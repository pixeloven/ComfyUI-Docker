# fetch — verified model materialisation

Downloads the model files a package declares, checks every one against its
`sha256`, and does nothing at all on the second run.

Dependencies: `curl`, `sha256sum`, `yq`. No Python, no language runtime — the
image is ~48 MB and can be dropped into an initContainer, a compose service, or
a Helm pre-install hook without imposing anything on the consumer.

## Why not just `comfy-lock.yaml`

comfy-lock's **documented** format does have somewhere to put a content hash:

```yaml
    hashes:
      - hash: [hash]
        type: [AutoV1, AutoV2, SHA256, CRC32, and Blake3]
```

so `emit-comfy-lock.sh` fills it in, and the projection is *not* lossy on the
thing that matters most. What it cannot carry is everything else a package
knows: additional ranked sources to fail over to, credential kinds, file sizes,
install roles beyond the single `type` field.

The larger gap is that **upstream comfy-lock is a spec, not a working feature.**
As of `comfy-cli` HEAD:

- `ComfyLockYAMLStruct.models` is initialised `[]` and never appended to, so
  `save_yaml` writes an empty model list;
- the dataclass carries a singular scalar `hash`, not the README's
  `hashes: [{hash, type}]`, so spec and implementation disagree;
- `load_metadata()` returns a raw dict that nothing consumes;
- `custom_nodes` is `[]` in code but a ComfyUI-Manager-shaped dict in the README
  and in real lock files.

It has been `# Todo: Add custom node fields for comfy-lock.yaml` in
`workspace_manager.py` for some time. So nothing yet reads a comfy-lock to fetch
anything — here or upstream — and a hash sitting in a file no reader checks
verifies nothing.

That is what a *package* is for: the same information, in a format that a
fetcher actually consumes, with the verification performed. It matters more for
model weights than for most payloads — **a wrong-but-plausible model file is
worse than a missing one.** A missing file fails loudly at load. A wrong one
renders subtly wrong images forever, with no error anywhere.

```yaml
package: qwen-image
version: 1
description: Qwen-Image 20B text-to-image.
models:
  - name: qwen-image-vae
    role: vae
    install: models/vae/
    files:
      - path: vae/qwen_image_vae.safetensors
        sha256: a70580f0213e67967ee9c95f05bb400e8fb08307e017a924bf3441223e023d1f
        size_bytes: 253806246
        sources:                       # ranked best-first, tried in order
          - kind: huggingface_canonical
            url: https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors
```

Schema: [`models/packages/package.schema.json`](../../models/packages/package.schema.json).

`comfy-lock.yaml` in this repository is **generated** from `models/packages/` by
`emit-comfy-lock.sh`, and CI fails if the two disagree. The projection is lossy
on purpose: what comfy-lock cannot express is dropped rather than smuggled into
a comment, so what remains is exactly what `comfy-cli` and friends consume.

## Usage

```sh
fetch-package.sh <package.yaml> <dest-root> [--apply]   # dry run without --apply
check-packages.sh <config-dir>                          # every held file is claimed by exactly one package
emit-comfy-lock.sh <packages-dir>                       # render packages down to comfy-lock's models:
```

Docker:

```sh
docker run --rm \
  -v "$PWD/models/packages:/packages:ro" \
  -v comfyui-models:/models \
  ghcr.io/pixeloven/comfyui/fetch:latest \
  /packages/qwen-image.yaml /models --apply
```

Credentials come from the environment — `CIVITAI_TOKEN`, `HF_TOKEN` — never from
the package. A package is published; a token is not. A source needing a token you
do not have is **skipped rather than attempted**, because an unauthenticated
Civitai request returns an HTML error page with HTTP 200, which would be written
to disk and then fail the hash check with a message naming the wrong cause.

A file with **no** `sources` is reported as `skipped`, never `failed` — its
absence is a recorded, accepted risk, and a check that can never pass gets
disabled.

## Things that will bite you

- **`yq` version matters.** 4.47 emits `"\t"` inside an expression literally;
  4.53 interprets it as a tab. The record format here therefore uses no escapes
  at all — one field per line, with a source count — and the script asserts that
  the number of records it read equals the number of files the package declares.
  Without that assertion, a parser that matches nothing reports `0 failed` and
  exits 0.
- **`x-linked-etag` is the sha256, but only on the first hop.** Following the
  redirect to the CDN gives you the Xet content-address instead — a different
  value that looks equally plausible. Resolve hashes with `curl -sI` (no `-L`).
- **The destination must be writable before any request.** Checked once, so an
  unwritable volume is reported as one failure naming the real cause rather than
  as one transfer failure per source tried against it.
- **Bind mounts and DinD.** If you run this from CI where the job's filesystem is
  not the Docker host's, `-v "$(mktemp -d):/w"` silently mounts an empty
  directory. `verify.sh` is piped in over stdin for exactly that reason.
