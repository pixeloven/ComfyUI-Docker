---
name: comfy-manifest
description: Author comfy.yaml and generate locks — source forms, when `as:` is required, how profiles compose, and the mistakes that fail silently.
---

# Authoring `comfy.yaml`

`comfy.yaml` is hand-authored and declares **intent**. `comfy-lock.yaml` records
the **resolution** and is generated — never hand-edit a lock.

```
models/  --comfyctl fetch build-->  comfy.yaml  --comfyctl fetch resolve-->  comfy-lock.yaml  --comfyctl fetch fetch-->  disk
```

The command is `comfyctl fetch <verb>`. Up to 3.x it was `comfyfetch <verb>`, with
the same verbs and flags. 4.0.0 removed that command and left no alias, so
rewrite any old invocation you find. Without installing anything, pinned to a tag:
`uvx --from 'git+https://github.com/pixeloven/ComfyUI-Docker@v4.0.0#subdirectory=services/comfyctl' comfyctl fetch --help`.

**Never let an installer resolve `comfyfetch` from a package index.** Neither
`comfyctl` nor `comfyfetch` is registered on PyPI. Use the `uvx` line above, which
takes comfyfetch from the same commit, or install the release's `comfyctl` wheel
with `--with <comfyfetch wheel url>`. Don't use `pip install` on the git
subdirectory, or a `comfyctl` wheel on its own.

- **`fetch` is a dry run by default.** `comfyctl fetch fetch <lock> <ComfyUI root>`
  only reports; add `--apply` to download. The root is the ComfyUI root, not
  `models/`, because lock paths begin `models/`.
- **`facts`** writes a `<lineage>.facts.yaml` sidecar per source file, recording
  what the safetensors header says against what the publisher claims for the
  file's hash: `comfyctl fetch facts models/ comfy-lock.yaml --store <root>`
  (or `--headers <json>`). It needs the network.
- **`-o json`** on any verb (after the verb, not after `fetch`) prints the result as
  stable JSON on stdout. Progress stays on stderr, so the output parses.
- **Exit codes:** `0` did what was asked, `1` a real failure (unresolved source,
  hash mismatch, manifest and lock disagree), `2` a bad request (missing file,
  unknown profile, incompatible flags).

`comfy.yaml` may itself be generated. Past a few hundred lines a single manifest
stops working — every family conflicts with every other on edit — so `build`
assembles it from one file per lineage under a directory you lay out:

```sh
comfyctl fetch build models/ -O comfy.yaml
comfyctl fetch build models/ -O comfy.yaml --check     # CI; the manifest is committed
```

A source file may carry **`summary:`** — the judgement a file list cannot
express ("two generations, NOT interchangeable"). `build` re-attaches it above
that lineage's groups so it reaches the artifact, which is where the manifest is
actually read.

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
comfyctl fetch resolve comfy.yaml > comfy-lock.yaml
comfyctl fetch resolve comfy.yaml --profile sdxl --from-lock comfy-lock.yaml > locks/sdxl.yaml
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
- **A stale generated manifest.** If `comfy.yaml` is built from `models/`, an
  edit to a source file that is never rebuilt resolves the OLD models. Nothing
  errors — `resolve` is perfectly happy with a manifest that is merely out of
  date. `comfyctl fetch build --check` is the only thing that says so.
- **An unprefixed custom key.** File and group entries reject unknown keys, so
  your own metadata needs an `x-` prefix (`x-triggers:`, `x-generation:`). That
  rejection is deliberate — it is what makes `instal:` an error instead of a
  silent no-op.
- **Deriving locks independently.** `comfyctl fetch check --parent` asserts a
  profile lock is a verbatim subset of the full lock. Without it, locks made
  minutes apart can pin different upstream commits and every one of them passes
  `check` on its own.
- **Trusting a filename.** The same name routinely carries different bytes.
  `flux1-krea-dev` had a Civitai source that now 404s and an identical-byte copy
  on HuggingFace — only the hash proved they were the same file.
