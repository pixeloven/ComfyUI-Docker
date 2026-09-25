---
name: comfyui-docker-conventions
description: ComfyUI-Docker's repository facts and project invariants — bake targets and profiles, image tag model, CUDA/torch/SageAttention coupling, data volumes, entrypoint UID contract, container standards, dependency rules, verification commands. Load before editing a Dockerfile, docker-bake.hcl, entrypoint/startup, an example compose file, or services/fetch.
---

# ComfyUI-Docker conventions

Facts here were checked against the files named beside them. When a file and
this skill disagree, the file is right, so fix the skill in the same change.

## Repository map

| Path | What it is |
|---|---|
| `docker-bake.hcl` | Every image target and group. Pins `COMFYUI_VERSION` and the SageAttention wheels. |
| `services/runtime/` | Base images: `dockerfile.cuda.runtime` (`nvidia/cuda:13.0.2-base-ubuntu24.04`) and `dockerfile.cpu.runtime` (`ubuntu:24.04`, used for cpu, **rocm and xpu**) |
| `services/comfy/core/` | `dockerfile.comfy.core` (a builder stage, then the `core` stage), `entrypoint.sh`, `startup.sh` |
| `services/comfy/complete/` | `dockerfile.comfy.cuda.complete`, built `FROM core`, and `extra-requirements.txt` |
| `services/mcp/` | `dockerfile.comfy.mcp`, which packages upstream `joenorton/comfyui-mcp-server` (`MCP_VERSION` is set in bake). It is standalone on `python:3.12-slim`; see its README. |
| `services/fetch/` | `comfyfetch` (Python, Typer, uv project; verbs `resolve`, `fetch`, `check`, `build`, `facts`), its bundled JSON schemas, its tests, and its image (`python:3.13-alpine`) |
| `comfy.yaml`, `comfy-lock.yaml`, `locks/` | The model manifest (intent), the generated lock (resolution), and the derived profile locks (`locks/preview.yaml`) |
| `examples/{core-gpu,complete-gpu,core-cpu,core-amd,core-intel}/` | One standalone Compose deployment per profile, each with `.env.example` and `extra_model_paths.yaml` |
| `skills/`, `.claude-plugin/`, `package.json` | The **published** consumer skills plugin. See `skills/README.md`. |
| `.agents/skills/` (and `.claude/skills/` symlinks) | Local skills for agents working on this repo. Not published. |
| `VERSION`, `VERSIONING.md`, `CHANGELOG.md` | The single release line |
| `.github/workflows/ci.yml`, `nightly.yml` | The only publishers |

## Images and profiles

Images are `ghcr.io/pixeloven/comfyui/<name>`. The bake targets:

| Group | Targets | Notes |
|---|---|---|
| `runtime` | `runtime-{cuda,cpu,rocm,xpu}` | The base layers |
| `core` | `core-{cuda,cpu,rocm,xpu}` | ComfyUI plus torch from `TORCH_INDEX` = `cu130` / `cpu` / `rocm7.2` / `xpu` |
| `cuda` | `runtime-cuda`, `core-cuda`, `complete-cuda` | `complete` = core + `extra-requirements.txt`, portable across CUDA GPUs |
| `cuda-arch` | `complete-cuda-sm{80,86,89,90,120}` | Complete + one SageAttention 2.2.0 wheel per compute capability. Built separately so an ABI break cannot block the generic CUDA images. |
| `mcp`, `fetch` | `mcp`, `fetch` | Independent of the runtime images |
| `all` | all of the above | |

The five examples map to `core:cuda`, `complete:cuda`, `core:cpu`, `core:rocm`
and `core:xpu`. `README.md` documents them, and `docs/user-guides/performance.md`
has the SageAttention architecture table.

**Version coupling.** The SageAttention wheels come from
`pixeloven/SageAttention-Wheels` and are built for **cu130, torch 2.13.0 and
cp312**, each pinned by URL *and* sha256. That release can be re-uploaded in
place, which is why the sha256 pin matters. Core installs torch **unpinned** from the
`TORCH_INDEX` wheel index, and Python comes from Ubuntu 24.04 (3.12). If the
index moves torch, or the CUDA base or Python changes, the `cuda-arch` build
fails its import check. The generic CUDA images still publish, so the `cuda-sm*`
tags quietly stop moving until the wheels are rebuilt.

## Tag model

These come from `VERSIONING.md` and the `context` job in `ci.yml`. A tag answers exactly one question:

| Tag | Means | Written by |
|---|---|---|
| `<runtime>-<sha8>` + `<runtime>-latest` | a build of our `main` | push to `main` (`PUBLISH_LATEST=true` only there) |
| `<runtime>-X.Y.Z` | our packaging, released | a `vX.Y.Z` tag |
| `<runtime>-nightly` | upstream ComfyUI **master**, resolved to a commit | `nightly.yml`, 02:00 UTC; Sundays bypass cache |

`mcp` and `fetch` use the same scheme without the runtime prefix, and `fetch`
also gets `X.Y`. A PR build never pushes. **What ComfyUI is inside** is stated
only by the `org.opencontainers.image.version` label, which is set from
`COMFYUI_VERSION` (tag, branch or commit SHA; a release requires `vX.Y.Z`).
There is no date tag.

## Data contract

- Volumes, with their example env override: `/app/models` (`COMFY_MODEL_PATH`), `/app/custom_nodes`
  (`COMFY_CUSTOM_NODE_PATH`), `/app/datasets` (`COMFY_DATASET_PATH`), `/app/input` (`COMFY_INPUT_PATH`),
  `/app/output` (`COMFY_OUTPUT_PATH`), `/app/temp` (`COMFY_TEMP_PATH`), `/app/user` (`COMFY_USER_PATH`).
  Config is `extra_model_paths.yaml`, mounted read-only at `/app/extra_model_paths.yaml`.
  The ComfyUI database is `/app/user/comfyui.db`.
- `startup.sh` flags: `--base-directory /app`, `COMFY_PORT` (8188),
  `COMFY_ENABLE_MANAGER` (true), `COMFY_ENABLE_ASSETS` (true), `--cpu` when
  `COMFY_RUNTIME=cpu`, and `CLI_ARGS` as the whitespace-split escape hatch.
- Credentials: never in an image or a lock. `comfy.yaml`'s `auth:` maps a host to a
  `${ENV_VAR}` reference, and the schema rejects a literal. The examples pass
  `HF_TOKEN` and `CIVITAI_TOKEN` to the opt-in `fetch` service
  (`docker compose --profile models up`).

## Entrypoint contract (`services/comfy/core/entrypoint.sh`)

- **Installed** root-owned, mode 0755, at `/usr/local/bin/entrypoint.sh` (the image's
  `ENTRYPOINT`). It runs as root, so it must never live under `/app`, which is
  world-writable. Its first line sets a fixed system `PATH`, so root-path commands
  never resolve from the venv; both paths re-activate the venv before exec.
- **Started as root** (the Compose default): `PUID`/`PGID` default to 1000:1000.
  Anything non-numeric or above 65534 exits 1 immediately, and `PUID=0` prints a warning.
  The group and user are created only if missing: an existing entry with that ID is
  reused, and a new one is named `comfy-<PGID>` / `comfy-<PUID>`, because the image's
  own `comfy` (1000:1000) already holds the plain name. Nothing downstream uses the
  names: gosu and `chown` take the numeric IDs, and a created user's home is `/app`,
  which gosu exports as `HOME` (a reused user keeps its own home, e.g. 33 → `/var/www`).
  Creating an entry needs writable `/etc/passwd` and `/etc/group`. It then sets both
  to 644 (non-fatal, for when they are mounted read-only) and warns if they are still
  world-writable. `chown -h` is **non-recursive** and
  covers only `/app`, `/app/ComfyUI` and each existing volume root that is not a
  symlink, because model stores run to terabytes; `-h` means it never follows a
  symlink. It logs `Starting with UID:GID = x:y`, then
  `exec gosu "$PUID:$PGID"`.
- **Started non-root** (Kubernetes `runAsUser`): no gosu. It appends `/etc/passwd` and
  `/etc/group` entries when the UID or GID has none, logs `Starting as non-root
  UID:GID = x:y`, and execs directly.
- `dockerfile.comfy.core` makes that work: venv `site-packages` dirs and `bin`,
  `.cache`, the volume roots, `/app`, `/app/ComfyUI`, `/etc/passwd` and `/etc/group`
  are world-writable, and `PYTHONDONTWRITEBYTECODE=1`. `complete` re-applies the
  venv permissions after its own installs, and any new install layer must do the same.
- `dockerfile.comfy.core` also drops setuid/setgid bits from every file in its final
  stage, since nothing in the image needs them. The last `RUN` of `core` and of
  `complete` asserts that none remain, so a later apt layer fails the build rather
  than silently undoing the strip; a new stage needs the same assertion. The examples
  run every service with `no-new-privileges:true`.

## Container standards

- **Base images:** official `nvidia/cuda` for CUDA. `ubuntu:24.04` for cpu, rocm and xpu,
  with the accelerator coming from PyTorch's official wheel index (not an official
  Python image). `python:*-slim` / `-alpine` for `mcp` and `fetch`.
- **Multi-stage:** the venv, ComfyUI and torch are built in `builder` and copied into
  `core`. The runtime base keeps `build-essential` and `python3-dev`.
- **Layer order:** base, then apt, then torch, then the ComfyUI clone. Nightly busts only the
  clone layer, which is why a weekly cache-free rebuild exists.
- **Arbitrary UID:** see *Entrypoint contract*. No image defines a `HEALTHCHECK`.

## Dependency rules

- Extra Python packages go in a requirements file (`extra-requirements.txt` for
  complete), never inline `pip install` in a Dockerfile. There are two exceptions,
  and both are deliberate: the torch family is installed with `--index-url` (never
  `--extra-index-url`, which lets PyPI's torch win and splits the CUDA ABI), and
  SageAttention is installed from a sha256-checked wheel.
- **Custom nodes are not baked into images.** They are installed at runtime onto the
  `/app/custom_nodes` volume (through Manager or a mount). `complete` pre-installs the
  Python *dependencies* common nodes need, because a missing import crash-loops ComfyUI.
  `comfy.yaml` covers **models only** today. `comfy-lock.yaml` has a `custom_nodes`
  section in comfy-cli's shape, but `comfyfetch` does not act on it.
- Pins that move only on purpose: `COMFYUI_VERSION`, the SageAttention URL and sha256 values,
  `MCP_VERSION` and the MCP SDK bound in `services/mcp/constraints.txt`, the `sam2` commit in `extra-requirements.txt`, and GitHub Action versions
  (exact semver tags, bumped by Dependabot).

## Project invariants

These carry forward what was still true of the retired spec-kit constitution (v1.0.0), updated to the current repo:

1. **Containers first, one per profile.** Multi-stage builds, and every published
   image runs on its own.
2. **Profile isolation.** Each example is its own Compose project, with its own
   container name and `./data`. A profile difference is a bake `arg` or a
   documented env var, never shared runtime state.
3. **GPU and performance transparency.** Accelerator-specific work stays in its own
   target. SageAttention takes effect only in `cuda-sm*` with `--use-sage-attention`,
   and never enters the generic, CPU, ROCm or XPU images. Resource needs are
   documented in `README.md` and `docs/user-guides/performance.md`, but not yet
   per profile.
4. **Data boundaries.** User data lives on volumes and survives a rebuild. Every
   path can be overridden, and no user data or credentials go into an image.
5. **Provenance.** Only CI publishes. Each tag answers one question (see *Tag model*),
   and `VERSIONING.md` is authoritative for semver. Treat any other breaking change
   to deployment (an env var, a volume path, a tag, a removed profile or example)
   as a protected seam for the owner to classify.
6. **Workflow.** A change to shared layers (`runtime`, `core`, `entrypoint.sh`,
   `startup.sh`) affects every profile, so verify every example it can reach.
   Compose changes stay backward compatible with existing volume mounts. A new env
   var is documented in `README.md`, the relevant user guide, and every example's
   `.env.example`. Moving `COMFYUI_VERSION` is a deliberate, reviewed commit, and the
   nightly is what follows upstream. No automation bounds how far the stable pin
   lags: it sat five weeks behind before 2.3.0.

## Verification commands

These match what CI runs:

```sh
cd services/fetch && uv run pytest -q            # add -m "not network" offline; gated cases skip without HF_TOKEN
cd services/fetch && uv run comfyfetch check ../../comfy.yaml ../../comfy-lock.yaml
uvx --from ./services/fetch comfyfetch check comfy.yaml locks/preview.yaml --profile preview --parent comfy-lock.yaml
make validate                                    # bake --print all + every example's compose config
docker buildx bake <target|group> --load         # or make cuda / cpu / rocm / xpu
docker run --rm -v "$PWD":/repo -w /repo rhysd/actionlint:1.7.7 -color
```

`uv run` creates `services/fetch/.venv`, which `.gitignore` covers (`.venv/`), but
stage files by name anyway. No Python or shell linter or formatter is configured. The one
exception is actionlint, which runs shellcheck over the workflow `run:` blocks;
`entrypoint.sh` and `startup.sh` are not linted.
