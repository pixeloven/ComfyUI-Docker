# Runtime Contract

What a deployment of the `core` and `complete` images can rely on: the environment
variables, the volume paths, the port, the readiness endpoint, and how the container
behaves depending on the user it starts as.

A deployment that works on one release must keep working on the next. Changing
anything on this page in a way that breaks one is a **major** version (see
[What counts as a breaking change](#what-counts-as-a-breaking-change)).

Every fact here comes from `services/comfy/core/entrypoint.sh`,
`services/comfy/core/startup.sh`, `services/comfy/core/dockerfile.comfy.core` and the
`examples/`. If this page and those files disagree, the files are right, and this
page has a bug.

## At a Glance

| Contract | Value |
|----------|-------|
| Image | `ghcr.io/pixeloven/comfyui/core` or `.../complete`, tag `<runtime>-<version>` (see [Building Images](building.md)) |
| Port | `8188`, set by `COMFY_PORT`, listening on all interfaces |
| Readiness | `GET /system_stats` returns `200` |
| Data | Seven volume roots under `/app` (see [Volumes](#volumes)) |
| User, started as root | Drops to `PUID:PGID` (default `1000:1000`) through `gosu` |
| User, started as non-root | Runs as the UID it was given. `PUID`/`PGID` are ignored and nothing is `chown`ed |
| Health check | None. The image defines no `HEALTHCHECK` |

## Environment Variables

The variables fall into three groups. Only the first changes what the container does.

### Read by the Container

| Variable | Default | Effect | Read by |
|----------|---------|--------|---------|
| `PUID` | `1000` | UID that ComfyUI runs as. **Only when the container starts as root.** It must be an integer from 0 to 65534, or the container exits 1. `0` is allowed, with a warning | `entrypoint.sh` |
| `PGID` | `1000` | GID that ComfyUI runs as. Same rules and the same root-only caveat as `PUID` | `entrypoint.sh` |
| `COMFY_PORT` | `8188` | Passed as `--port` | `startup.sh` |
| `COMFY_ENABLE_MANAGER` | `true` | Only the exact string `true` adds `--enable-manager`. Any other value, including `True` or `1`, disables the Manager | `startup.sh` |
| `COMFY_ENABLE_ASSETS` | `true` | Only the exact string `true` adds `--enable-assets` (the Assets API, sidebar and index) | `startup.sh` |
| `CLI_ARGS` | *(empty)* | Extra ComfyUI arguments, split on whitespace and appended **last**. Quoting inside the value is not honoured, so an argument can't contain a space | `startup.sh` |
| `COMFY_RUNTIME` | set by the image: `cuda`, `cpu`, `rocm` or `xpu` | `cpu` adds `--cpu`. Every other value adds nothing. You don't normally set this, because each image already carries the right value | `startup.sh` |

Because `CLI_ARGS` comes last, a single-value flag in it overrides the one
`startup.sh` sets, for example `--database-url`. Don't change the port that way.
Set `COMFY_PORT` instead, because the Compose examples use that variable for the
published port too.

On the CPU image, `--cpu` is always passed. ComfyUI treats `--cpu`, `--lowvram`,
`--novram`, `--highvram` and `--gpu-only` as mutually exclusive, so putting any of
the others in `CLI_ARGS` on the CPU image makes ComfyUI exit with an argument error.

### Set by the Image

These are set with `ENV` in `dockerfile.comfy.core`. They are not settings. They are
listed so that nobody mistakes them for settings, or overrides one without knowing
what depends on it.

| Variable | Value |
|----------|-------|
| `COMFYUI_VERSION` | The ComfyUI ref built into the image. `org.opencontainers.image.version` carries the same value |
| `COMFY_RUNTIME` | `cuda`, `cpu`, `rocm` or `xpu` (see above) |
| `HOME` | `/app` |
| `XDG_CACHE_HOME` | `/app/.cache` |
| `VENV_PATH` | `/app/.venv` (the entrypoint activates `/app/.venv` directly, not through this variable) |
| `PATH` | Starts with `/app/.venv/bin` |
| `PYTHONPATH` | `/app/ComfyUI` |
| `PYTHONDONTWRITEBYTECODE` | `1`, so an arbitrary UID never fails trying to write `.pyc` files |

`CLI_ARGS` and `COMFY_PORT` also have image defaults (empty and `8188`), which are the
defaults in the table above.

### Read by Docker Compose Only

The examples' `docker-compose.yml` files interpolate these variables. The container
never sees them. Under Kubernetes or a plain `docker run` they do nothing.

| Variable | Default | Used for | Examples |
|----------|---------|----------|----------|
| `COMFY_MODEL_PATH` | `./data/models` | Host side of `/app/models` (also mounted by `fetch`) | all five |
| `COMFY_CUSTOM_NODE_PATH` | `./data/custom_nodes` | Host side of `/app/custom_nodes` | all five |
| `COMFY_DATASET_PATH` | `./data/datasets` | Host side of `/app/datasets` | all five |
| `COMFY_INPUT_PATH` | `./data/input` | Host side of `/app/input` | all five |
| `COMFY_OUTPUT_PATH` | `./data/output` | Host side of `/app/output` | all five |
| `COMFY_TEMP_PATH` | `./data/temp` | Host side of `/app/temp` | all five |
| `COMFY_USER_PATH` | `./data/user` | Host side of `/app/user` | all five |
| `COMFY_IMAGE` | the example's image | The `comfyui` service's image | all five |
| `COMFY_FETCH_IMAGE` | `ghcr.io/pixeloven/comfyui/fetch:latest` | The opt-in `fetch` service's image | all five |
| `COMFY_LOCK` | `../../locks/preview.yaml` | The lock the `fetch` service applies | all five |
| `HF_TOKEN`, `CIVITAI_TOKEN` | *(empty)* | Passed to the `fetch` service only, for gated downloads | all five |
| `VIDEO_GID`, `RENDER_GID` | `44`, `109` | `group_add` for GPU device access | `core-amd`, `core-intel` |
| `HSA_OVERRIDE_GFX_VERSION` | *(empty)* | Passed into the container for the ROCm runtime, not read by the scripts | `core-amd` |

The GPU examples (`core-gpu`, `complete-gpu`) also set `NVIDIA_VISIBLE_DEVICES=all`
and `NVIDIA_DRIVER_CAPABILITIES=compute,utility` inside the compose file. Those two
are hard-coded, not interpolated.

`PUID`, `PGID`, `COMFY_PORT`, `COMFY_ENABLE_MANAGER`, `COMFY_ENABLE_ASSETS` and
`CLI_ARGS` go through Compose too: each example passes them into the container, with
the defaults from the first table. The `fetch` service runs as `${PUID}:${PGID}`.

### Which `.env.example` Documents What

| Variable | core-gpu | complete-gpu | core-cpu | core-amd | core-intel |
|----------|:--:|:--:|:--:|:--:|:--:|
| `PUID`, `PGID`, `COMFY_PORT`, `COMFY_ENABLE_MANAGER`, `COMFY_ENABLE_ASSETS`, `CLI_ARGS` | ✓ | ✓ | ✓ | ✓ | ✓ |
| The seven `COMFY_*_PATH` variables | ✓ | ✓ | ✓ | ✓ | ✓ |
| `COMFY_LOCK`, `HF_TOKEN`, `CIVITAI_TOKEN` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `VIDEO_GID`, `RENDER_GID` | – | – | – | ✓ | ✓ |
| `HSA_OVERRIDE_GFX_VERSION` | – | – | – | ✓ | – |
| `COMFY_IMAGE`, `COMFY_FETCH_IMAGE` | – | – | – | – | – |

`COMFY_IMAGE` and `COMFY_FETCH_IMAGE` are read by every compose file but documented in
no `.env.example`. `COMFY_IMAGE` is covered in [Running Containers](running.md) and
[Building Images](building.md). `COMFY_RUNTIME` is in none of them, because the image
sets it.

## Volumes

ComfyUI starts with `--base-directory /app`, so each data directory is a fixed path
under `/app`. The image creates all seven world-writable (`a+rwx`). You change **where
the data lives** by mounting something at the path; the path inside the container
itself can't be changed with an environment variable.

| Container path | Holds | Compose override (host side) | `chown`ed when started as root |
|----------------|-------|------------------------------|:--:|
| `/app/models` | Checkpoints, LoRAs, VAEs and every other model type | `COMFY_MODEL_PATH` | ✓ |
| `/app/custom_nodes` | Custom nodes, installed at runtime | `COMFY_CUSTOM_NODE_PATH` | ✓ |
| `/app/datasets` | Datasets for the native trainer | `COMFY_DATASET_PATH` | ✓ |
| `/app/input` | Uploaded and input images | `COMFY_INPUT_PATH` | ✓ |
| `/app/output` | Generated output | `COMFY_OUTPUT_PATH` | ✓ |
| `/app/temp` | Temporary files | `COMFY_TEMP_PATH` | ✓ |
| `/app/user` | Settings, saved workflows, and the database `comfyui.db` | `COMFY_USER_PATH` | ✓ |

Two more paths are part of the contract:

- **`/app/user/comfyui.db`**: `startup.sh` always passes
  `--database-url sqlite:////app/user/comfyui.db`, so the database lives on the
  `user` volume.
- **`/app/extra_model_paths.yaml`**: optional. When the file exists, `startup.sh`
  passes `--extra-model-paths-config /app/extra_model_paths.yaml`. The examples
  mount it read-only.

Nothing else under `/app` is meant to be a volume. `/app/ComfyUI` and `/app/.venv`
belong to the image.

## Port

ComfyUI listens on **`8188`** on all interfaces (`--listen` without an address, which
upstream treats as `0.0.0.0` and `::`).

To change the port, set `COMFY_PORT`. In the examples, Compose publishes the same
number on both sides (`"${COMFY_PORT}:${COMFY_PORT}"`), so one variable moves both:

```bash
COMFY_PORT=8189 docker compose up -d   # from within an examples/ directory
```

In Kubernetes, set `COMFY_PORT` in the container's `env` and use the same number for
`containerPort` and the probes. The image's `EXPOSE 8188` is metadata fixed at build
time; it doesn't follow `COMFY_PORT` and doesn't need to.

## Readiness: `/system_stats`

`GET /system_stats` returns `200` with a JSON body of system and device information.
It's upstream ComfyUI's route, served unmodified, and is also reachable as
`/api/system_stats`.

It makes a good readiness probe because of when it starts answering. ComfyUI loads
custom nodes, sets up the database, registers its routes, and only then opens the
port. A `200` therefore means the server is up with its nodes loaded, and the
`Connection refused` before that is expected. On a large `custom_nodes` volume that
first stage can take minutes.

```yaml
readinessProbe:
  httpGet:
    path: /system_stats
    port: 8188
```

The route was checked against upstream's `server.py` at the pinned `COMFYUI_VERSION`
(`v0.37.0`, in `docker-bake.hcl`), by reading the source. CI does not yet start an
image and call it. That check is planned in
[#100](https://github.com/pixeloven/ComfyUI-Docker/issues/100), and until it lands, a
`COMFYUI_VERSION` bump is the moment to confirm the route still exists.

The image defines no `HEALTHCHECK`, and this repo doesn't prescribe a liveness probe.
`/system_stats` shows that the server answers. It can't tell a wedged ComfyUI from a
busy one.

## Startup: Root versus Non-Root

`entrypoint.sh` chooses its path from the UID it is started as, not from any variable.
The two paths do different things to your volumes, so the difference matters.

### Started as Root

This is the default for Docker Compose and for `docker run` without `-u`. The image
has no `USER`, so it starts as root.

1. `PUID` and `PGID` default to `1000`. Each must be an integer from 0 to 65534,
   or the entrypoint prints an error and exits 1. `PUID=0` prints a warning and
   runs ComfyUI as root.
2. If a group already has `PGID`, or a user already has `PUID`, it reuses that entry.
   Otherwise it creates group `comfy-<PGID>` or user `comfy-<PUID>` (home `/app`),
   named for the ID because the image already has `comfy` as `1000:1000`.
3. It runs `chown PUID:PGID` on `/app`, on `/app/ComfyUI`, and on each of the seven
   volume roots that exists, skipping any volume root that is a symlink. This is **not recursive**: only the directory itself
   changes owner, never what's inside it, because a model store can be terabytes.
4. It logs `Starting with UID:GID = <PUID>:<PGID>`.
5. It runs `exec gosu PUID:PGID`, activates the venv, and execs `startup.sh`. No root
   process remains.

So on this path, each volume root ends up owned by `PUID:PGID`, **including the
host directory behind a bind mount**. Files and directories below the root keep
whatever owner they had. If older files belong to another UID, fix them once on the
host (`sudo chown -R`, see [Data Management](data.md#file-permissions)).

### Started as Non-Root

This covers Kubernetes `securityContext.runAsUser`, `docker run -u UID:GID`, and
Compose `user:`.

1. It logs `Starting as non-root UID:GID = <uid>:<gid>`.
2. If the UID has no `/etc/passwd` entry, it appends `comfyuser` with home `/app`. If
   the GID has no `/etc/group` entry, it appends `comfygroup`. Python and PyTorch
   look these up, and the image makes both files world-writable for exactly this.
3. It activates the venv and execs `startup.sh` directly.

On this path, **`PUID` and `PGID` are ignored, and nothing is `chown`ed**. The volumes
must already be writable by the UID or GID the container runs as:

- **Kubernetes:** set `fsGroup` in the pod `securityContext`. The kubelet makes each
  volume that supports it group-owned by that GID and group-writable. Without it, a
  freshly provisioned PVC is usually owned by root, and ComfyUI can't write to it.
  [`examples/kubernetes/`](../../examples/kubernetes/) shows the full shape.
- **`docker run -u`:** bind-mounted host directories must be writable by that UID or
  GID. Prepare them with `chown` or `chmod` on the host.

The root filesystem must stay writable on this path too. The entrypoint may append to
`/etc/passwd` and `/etc/group`, and the Manager installs custom-node dependencies into
the venv. `readOnlyRootFilesystem: true` breaks both.

### Side by Side

| | Started as root | Started as non-root |
|---|---|---|
| Identity comes from | `PUID` / `PGID` | `runAsUser` / `runAsGroup`, `-u`, or `user:` |
| `PUID` / `PGID` | Validated and used | Ignored |
| Users and groups | Created with `groupadd`/`useradd` if missing | Appended to `/etc/passwd` and `/etc/group` if missing |
| Volume ownership | `chown` of each volume root, not recursive | Untouched. The volumes must already be writable |
| Privilege drop | `gosu` | None needed |
| Log line | `Starting with UID:GID = x:y` | `Starting as non-root UID:GID = x:y` |

## What Counts as a Breaking Change

[`VERSIONING.md` → *What counts as major*](../../VERSIONING.md#what-counts-as-major)
is the rule. On this page, that covers:

- Renaming or removing a variable in [Read by the Container](#read-by-the-container),
  changing its default, or giving it a new meaning. The same goes for a
  `COMFY_*_PATH` or other Compose variable an example documents.
- Moving or removing a path in [Volumes](#volumes), or the database location.
- Changing the default port, or how `COMFY_PORT` sets it.
- Changing either startup path: validation, the `chown`, `gosu`, or how the non-root
  path handles an arbitrary UID.

`/system_stats` is upstream's route. If it ever changed, the change would arrive
through a `COMFYUI_VERSION` bump, and that bump would then break this contract.

Adding is never major. A new variable, volume, or image is a minor version. The
repository owner confirms how each change is classified.

---

**See Also:**
- [Running Containers](running.md) - Compose operations and `.env` configuration
- [Data Management](data.md) - Directory structure and permissions
- [Performance Tuning](performance.md) - What to put in `CLI_ARGS`
- [Kubernetes example](../../examples/kubernetes/README.md) - A minimal Deployment that takes the non-root path
