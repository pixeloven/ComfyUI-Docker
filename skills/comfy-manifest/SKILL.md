---
name: comfy-manifest
description: Author comfy.yaml and generate locks — source forms, when `as:` is required, how profiles compose, and the mistakes that fail silently.
---

# Authoring `comfy.yaml`

`comfy.yaml` is hand-authored and declares **intent**. `comfy-lock.yaml` records
the **resolution** and is generated — never hand-edit a lock.

```
comfy.yaml  --comfyfetch resolve-->  comfy-lock.yaml  --comfyfetch fetch-->  disk
```

## A file entry

```yaml
models:
  - name: qwen-image          # capability name; profiles reference this
    files:
      - source: hf:Comfy-Org/Qwen-Image_ComfyUI
        file: split_files/vae/qwen_image_vae.safetensors
        install: models/vae/   # a DIRECTORY, must start `models/` and end `/`
        type: vae
```

`install` is a directory because a human says "put it in vae"; the lock records
the resolved full path.

## Source forms

| form | needs | hash comes from |
|---|---|---|
| `hf:<owner>/<repo>` | `file:` | `x-linked-etag` header |
| `gh:<owner>/<repo>@<tag>` | `file:` (asset name) | release asset `digest`, else download-and-hash |
| `civitai:<modelVersionId>` | **`as:`** | `files[0].hashes.SHA256` |
| `https://…` | **`sha256:`** | nothing — you must state it |

Note the two that need something extra, because both fail in confusing ways:

- **`civitai:` requires `as:`.** The filename comes from the API, so without it
  the install path is not knowable offline — and `check` cannot run without
  network. The schema enforces this.
- **A direct URL requires `sha256:`.** Nothing about a bare URL can be resolved
  from headers. Resolve refuses rather than writing a lock entry that verifies
  nothing.

Use `as:` too whenever the local filename should differ from upstream's — e.g.
upstream `4x-UltraSharp.pth` stored as `4xUltrasharp_4xUltrasharpV10.pt`.

## `revision:` is the unresolved part

```yaml
        revision: main    # default; the lock pins this to a commit
```

This is the `^18` → `18.3.1` moment. Re-resolving after upstream moves is
*supposed* to produce a new commit and a new hash — which is why CI never
re-resolves as a drift check.

## Profiles compose by set union

```yaml
profiles:
  common:     [upscalers, shared-encoders]
  sdxl:       [common, sdxl-base]        # a member may be another profile
  everything: [sdxl, flux]
```

No inheritance, no overrides, no diamonds — none of it is needed because the
fetch is content-addressed: a model shared between profiles is declared once and
installed once.

Generate the full lock first, then **derive** the others so every profile pins
identical commits:

```sh
comfyfetch resolve comfy.yaml > comfy-lock.yaml
comfyfetch resolve comfy.yaml --profile sdxl --from-lock comfy-lock.yaml > locks/sdxl.yaml
```

Resolving each independently is the mistake: locks made minutes apart can
legitimately pin different commits.

## Credentials

```yaml
auth:
  civitai.com: ${CIVITAI_TOKEN}
  huggingface.co: ${HF_TOKEN}
```

Host-keyed, so **no model entry carries an auth field** — that is what keeps
`models[]` in the lock byte-for-byte comfy-cli's documented shape. Values must
be `${ENV_VAR}` references; the schema rejects a literal so a token cannot be
committed.

A host listed here whose variable is unset does **not** block public files.

## Mistakes that fail quietly

- **Hand-editing a lock.** It is generated. The sha256 in it then describes
  bytes nobody verified.
- **Editing `comfy.yaml` without regenerating.** The fetcher reads the lock, so
  your new model is simply never fetched and nothing says so.
- **Assuming a gated repo is missing.** `black-forest-labs` publishes as
  `gated: auto`; without a token it answers 401, which reads as "not found".
- **Trusting a filename.** The same name routinely carries different bytes.
  `flux1-krea-dev` had a Civitai source that now 404s and an identical-byte copy
  on HuggingFace — only the hash proved they were the same file.
