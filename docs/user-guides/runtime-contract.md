# Runtime Contract

What a deployment of the `core` and `complete` images can rely on: the environment
variables, the volume paths, the port, the readiness endpoint, and how the container
behaves depending on the user it starts as.

The separate `mcp` image has a shorter contract of its own, in
[The `mcp` Image](#the-mcp-image), and so do `mcp-convert`, in
[The `mcp-convert` Image](#the-mcp-convert-image), and `comfyctl`, in
[The `comfyctl` Image](#the-comfyctl-image).

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
| User, started as non-root | Runs as the UID it was given. `PUID`/`PGID` are ignored and the volumes are left as they are |
| Health check | None. The image defines no `HEALTHCHECK` |

## Environment Variables

The variables fall into three groups. Only the first is read by the image's scripts.

### Read by the Container

| Variable | Default | Effect | Read by |
|----------|---------|--------|---------|
| `PUID` | `1000` | UID that ComfyUI runs as. **Only when the container starts as root.** It must be an integer from 0 to 65534, or the container exits 1. `0` is allowed, with a warning | `entrypoint.sh` |
| `PGID` | `1000` | GID that ComfyUI runs as. Same rules and the same root-only caveat as `PUID` | `entrypoint.sh` |
| `COMFY_PORT` | `8188` | Passed as `--port` | `startup.sh` |
| `COMFY_ENABLE_MANAGER` | `true` | `true`, `1` or `yes`, in any case, adds `--enable-manager`. Any other value disables the Manager | `startup.sh` |
| `COMFY_ENABLE_ASSETS` | `true` | `true`, `1` or `yes`, in any case, adds `--enable-assets` (the Assets API, sidebar and index). Any other value leaves it off | `startup.sh` |
| `COMFY_ENABLE_NODE_VENV` | `true` | `true`, `1` or `yes`, in any case, runs ComfyUI from the [node venv](#the-node-venv), so the Python packages custom nodes install survive a recreate, and sets Manager's `use_uv` and `use_unified_resolver` to `False`. If the node venv can't be used, startup warns and falls back to the image's venv; it never exits over it. Any other value runs ComfyUI from the image's venv, as earlier releases did | `startup.sh` |
| `COMFY_MANAGER_SECURITY_LEVEL` | *(empty)* | Opt-in. `strong`, `normal`, `normal-` or `weak` is written to `security_level` in Manager's `config.ini` at every start. Empty leaves the file's own value, which is `normal` unless someone changed it. Any other value makes the container exit 1. See [Manager Security](#manager-security) | `startup.sh` |
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
| `HOME` | `/app`. A root start with an existing system user's `PUID` replaces it (see [What Startup Promises](#what-startup-promises)) |
| `XDG_CACHE_HOME` | `/app/.cache` |
| `VENV_PATH` | `/app/.venv` (the entrypoint activates `/app/.venv` directly, not through this variable) |
| `PATH` | Starts with `/app/user/__node_venv/bin`, then `/app/.venv/bin`. The first finds nothing until startup has made the [node venv](#the-node-venv) |
| `PYTHONPATH` | `/app/ComfyUI` |
| `PYTHONDONTWRITEBYTECODE` | `1`, so an arbitrary UID never fails trying to write `.pyc` files |

`CLI_ARGS` and `COMFY_PORT` also have image defaults (empty and `8188`), which are the
defaults in the table above.

### Read by Docker Compose

The examples' `docker-compose.yml` files interpolate these variables. The scripts in
the image never read them, and under Kubernetes or a plain `docker run` they do
nothing. All but one stay outside the container: `core-amd` passes
`HSA_OVERRIDE_GFX_VERSION` through to the ROCm runtime.

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
| `COMFYCTL_IMAGE` | `ghcr.io/pixeloven/comfyui/comfyctl:latest` | The opt-in `fetch` service's image ([The `comfyctl` Image](#the-comfyctl-image); the service runs `fetch fetch /comfy-lock.yaml /app --apply`). Up to 5.x this was `COMFY_FETCH_IMAGE`, which the examples no longer read | all five |
| `COMFY_LOCK` | `../../locks/preview.yaml` | The lock the `fetch` service applies | all five |
| `HF_TOKEN`, `CIVITAI_TOKEN` | *(empty)* | Passed to the `fetch` service only, for gated downloads | all five |
| `VIDEO_GID`, `RENDER_GID` | `44`, `109` | `group_add` for GPU device access | `core-amd`, `core-intel` |
| `HSA_OVERRIDE_GFX_VERSION` | *(empty)* | Passed into the container for the ROCm runtime, not read by the scripts | `core-amd` |

The GPU examples (`core-gpu`, `complete-gpu`) also set `NVIDIA_VISIBLE_DEVICES=all`
and `NVIDIA_DRIVER_CAPABILITIES=compute,utility` inside the compose file. Those two
are hard-coded, not interpolated.

`PUID`, `PGID`, `COMFY_PORT`, `COMFY_ENABLE_MANAGER`, `COMFY_ENABLE_ASSETS`,
`COMFY_ENABLE_NODE_VENV`, `COMFY_MANAGER_SECURITY_LEVEL` and `CLI_ARGS` go through
Compose too: each example passes them into the container, with
the defaults from the first table. The `fetch` service runs as `${PUID}:${PGID}`.

### Which `.env.example` Documents What

| Variable | core-gpu | complete-gpu | core-cpu | core-amd | core-intel |
|----------|:--:|:--:|:--:|:--:|:--:|
| `PUID`, `PGID`, `COMFY_PORT`, `COMFY_ENABLE_MANAGER`, `COMFY_ENABLE_ASSETS`, `COMFY_ENABLE_NODE_VENV`, `COMFY_MANAGER_SECURITY_LEVEL`, `CLI_ARGS` | ✓ | ✓ | ✓ | ✓ | ✓ |
| The seven `COMFY_*_PATH` variables | ✓ | ✓ | ✓ | ✓ | ✓ |
| `COMFY_LOCK`, `HF_TOKEN`, `CIVITAI_TOKEN` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `VIDEO_GID`, `RENDER_GID` | – | – | – | ✓ | ✓ |
| `HSA_OVERRIDE_GFX_VERSION` | – | – | – | ✓ | – |
| `COMFY_IMAGE`, `COMFYCTL_IMAGE` | ✓ | ✓ | ✓ | ✓ | ✓ |

`COMFY_IMAGE` is also covered in [Running Containers](running.md) and
[Building Images](building.md). `COMFY_RUNTIME` is in none of them, because the image
sets it.

## Volumes

ComfyUI starts with `--base-directory /app`, so each data directory is a fixed path
under `/app`. The image creates all seven so that any runtime UID can write to them.
You change **where the data lives** by mounting something at the path; the path
inside the container itself can't be changed with an environment variable.

| Container path | Holds | Compose override (host side) | Made writable when started as root |
|----------------|-------|------------------------------|:--:|
| `/app/models` | Checkpoints, LoRAs, VAEs and every other model type | `COMFY_MODEL_PATH` | ✓ |
| `/app/custom_nodes` | Custom nodes, installed at runtime | `COMFY_CUSTOM_NODE_PATH` | ✓ |
| `/app/datasets` | Datasets for the native trainer | `COMFY_DATASET_PATH` | ✓ |
| `/app/input` | Uploaded and input images | `COMFY_INPUT_PATH` | ✓ |
| `/app/output` | Generated output | `COMFY_OUTPUT_PATH` | ✓ |
| `/app/temp` | Temporary files | `COMFY_TEMP_PATH` | ✓ |
| `/app/user` | Settings, saved workflows, and the database `comfyui.db` | `COMFY_USER_PATH` | ✓ |

Four more paths are part of the contract:

- **`/app/user/comfyui.db`**: `startup.sh` always passes
  `--database-url sqlite:////app/user/comfyui.db`, so the database lives on the
  `user` volume.
- **`/app/extra_model_paths.yaml`**: optional. When the file exists, `startup.sh`
  passes `--extra-model-paths-config /app/extra_model_paths.yaml`. The examples
  mount it read-only.
- **`/app/user/__node_venv`**: the [node venv](#the-node-venv), on the `user`
  volume. Startup makes it.
- **`/app/user/__manager`**: ComfyUI-Manager's own directory, with its
  `config.ini`. Manager makes it; startup writes the keys
  [The Node Venv](#the-node-venv) and [Manager Security](#manager-security) name.

ComfyUI never serves a directory under `/app/user` whose name starts with `__`
over HTTP: it reserves those names for system data.

Nothing else under `/app` is meant to be a volume. `/app/ComfyUI` and `/app/.venv`
belong to the image.

`/app/ComfyUI/custom_nodes` is a symlink to `/app/custom_nodes`, so comfy-cli
installs land on the volume. Run it as the runtime user (`docker exec -u <PUID> …`);
under root, the installed files are root-owned and ComfyUI fails on them with a
`PermissionError`. Don't bind-mount the symlink path, which silently hides the volume,
and don't list it in `extra_model_paths.yaml`, which loads every pack twice.

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

CI verifies this probe. The `smoke-cpu` job starts `core-cpu` on every pull request
that changes the images, on every push to `main`, and on every release tag. It fails
unless `/system_stats` answers with a success status (anything below `400`, as
`curl -f` reads it), so a `COMFYUI_VERSION` bump that dropped the route would fail it.
The check boots the CPU image only. On a release tag, a failure withholds the GitHub
Release, but the images are pushed in parallel and are not held back. `make smoke`
runs the same script (`tests/smoke/run.sh`) locally.

The image defines no `HEALTHCHECK`, and this repo doesn't prescribe a liveness probe.
`/system_stats` shows that the server answers. It can't tell a wedged ComfyUI from a
busy one.

## Startup: Root versus Non-Root

`entrypoint.sh` chooses its path from the UID it is started as, not from any variable.
The two paths do different things to your volumes, so the difference matters.

### What Startup Promises

These outcomes are the contract:

- **Any UID and GID from 0 to 65534 runs.** Started as root, ComfyUI runs as
  `PUID:PGID`. Started as non-root, it runs as the UID and GID it was given.
- **The runtime UID and GID have a passwd and group entry**, including a UID the
  image has never heard of. Python and PyTorch look these up.
- **`HOME` is `/app` on the non-root path, and for any entry the entrypoint
  creates on the root path.** A root start with a `PUID` that already belongs to a
  system user keeps that user's home directory from its passwd entry instead. For
  example, `PUID=33` gets `/var/www` and `PUID=65534` gets `/nonexistent`. That
  behaviour is long-standing and intended, not a defect.
- **Started as root, the volume roots are writable by the runtime UID** when
  ComfyUI starts, except one whose `chown` fails (a read-only mount, or
  root-squashed NFS). Started as non-root, making them writable is up to the deployer
  (see below).
- **Started as root, no root process remains** once ComfyUI is running, unless you
  ask for one with `PUID=0`.

How the entrypoint achieves these today is described below. That is
implementation, not contract: it includes the file permissions, how entries are
created, and the `chown`. Tightening permissions or changing the mechanism is **not**
a contract change, as long as these outcomes still hold.

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
   It changes an owner **only when it differs** from `PUID:PGID`, and if the `chown`
   fails, on a read-only mount (`:ro`) or a root-squashed NFS export, it prints a
   warning and carries on: that volume root keeps its owner, and ComfyUI can write
   to it only if that owner or its mode already allows it.
4. It keeps the supplementary groups the container was started with, such as
   Compose `group_add` or `docker run --group-add` (the `core-amd` and `core-intel`
   examples use them for `/dev/dri` and `/dev/kfd`). The runtime user joins each of
   those groups, and a GID with no name gets the group `comfy-<GID>`. GID 0 and
   `PGID` are never added as supplementary groups. If `PUID`
   belongs to an existing user whose own group isn't `PGID`, for example `PUID=1000`
   with `PGID=100`, the groups can't be kept on this path: the entrypoint prints a
   warning and ComfyUI runs without them. Start the container as non-root instead,
   with volumes already writable by that UID, since a non-root start changes no owner.
5. It logs `Starting with UID:GID = <PUID>:<PGID>`.
6. It runs `exec gosu`, activates the venv, and execs `startup.sh`. No root
   process remains.

So on this path, each writable volume root ends up owned by `PUID:PGID`, **including
the host directory behind a bind mount** when its owner was different. Files and directories below the root keep
whatever owner they had. If older files belong to another UID, fix them once on the
host (`sudo chown -R`, see [Data Management](data.md#file-permissions)).

### Started as Non-Root

This covers Kubernetes `securityContext.runAsUser`, `docker run -u UID:GID`, and
Compose `user:`.

1. It logs `Starting as non-root UID:GID = <uid>:<gid>`.
2. If the UID or GID has no passwd or group entry, it gets one, with home `/app`.
3. It activates the venv and execs `startup.sh` directly.

Supplementary groups, such as `group_add` or Kubernetes `supplementalGroups`, are
kept as the container runtime set them.

On this path, **`PUID` and `PGID` are ignored, and nothing is `chown`ed**. The volumes
must already be writable by the UID or GID the container runs as:

- **Kubernetes:** set `fsGroup` in the pod `securityContext`. The kubelet makes each
  volume that supports it group-owned by that GID and group-writable. Without it, a
  freshly provisioned PVC is usually owned by root, and ComfyUI can't write to it.
  [`examples/kubernetes/`](../../examples/kubernetes/) shows the full shape.
- **`docker run -u`:** bind-mounted host directories must be writable by that UID or
  GID. Prepare them with `chown` or `chmod` on the host.

The root filesystem must stay writable on this path too. Startup relies on it for a
UID the image doesn't know, and pip and Hugging Face write their caches to
`/app/.cache`. `readOnlyRootFilesystem: true` breaks both. Custom-node
dependencies no longer need it: they go to the [node venv](#the-node-venv), on a
volume.

### Side by Side

| | Started as root | Started as non-root |
|---|---|---|
| Identity comes from | `PUID` / `PGID` | `runAsUser` / `runAsGroup`, `-u`, or `user:` |
| `PUID` / `PGID` | Validated and used | Ignored |
| Users and groups | Created with `groupadd`/`useradd` if missing | An entry is provided if missing, with home `/app` |
| Volume roots | Made writable by `PUID:PGID` (today, a non-recursive `chown`) | Untouched. The volumes must already be writable |
| Privilege drop | `gosu` | None needed |
| Log line | `Starting with UID:GID = x:y` | `Starting as non-root UID:GID = x:y` |

### What Does Not Survive a Restart

Anything written outside the volumes lives in the container's writable layer:

- the caches under `/app/.cache` (`XDG_CACHE_HOME`)
- anything installed into `/app/.venv` itself: with
  `COMFY_ENABLE_NODE_VENV` off, every custom-node dependency; with it on, only
  what someone installs with the image's own interpreter, such as
  `/app/.venv/bin/pip`

That layer is lost whenever the container is recreated. In Compose, that happens when
`docker compose up` replaces the container, for example after a pull. In Kubernetes,
it happens on every container restart and every time the pod is rescheduled. The
custom nodes themselves stay on `/app/custom_nodes`, and, with the node venv on (the
default), so do the Python packages they install
([#115](https://github.com/pixeloven/ComfyUI-Docker/issues/115)).

### Hardening

We recommend turning off privilege escalation for the ComfyUI container:
`no-new-privileges:true` under `security_opt` in Compose, or
`allowPrivilegeEscalation: false` in the Kubernetes container `securityContext`.
Both startup paths work with it.

Run `docker exec` and `kubectl exec` sessions as the runtime user, not as root: for
example `docker exec -u "$PUID:$PGID" …`, or `kubectl exec` into a pod that already
runs as `runAsUser`.

## The Node Venv

Custom nodes are installed at runtime, by hand or by an agent: through Manager's UI,
`cm-cli`, or `git clone` into `/app/custom_nodes`. Their Python dependencies go into
the **node venv**, `/app/user/__node_venv`, so they survive a recreate along with
the nodes. Nothing in this repository installs custom nodes for you, and nothing
reads a lock's `custom_nodes` section.

**What it is.** A Python venv on the `user` volume, layered over the image's
`/app/.venv`. It has no packages of its own until something installs one, and a
`.pth` file puts the image's `site-packages` after its own on `sys.path`. So pip,
run from it, sees every package the image has, installs only what is missing, and
installs it into the node venv. When a pack needs another version of a package the
image has, pip installs that version into the node venv too, and it wins over the
image's (see [Shadowed image packages](#shadowed-image-packages)). The image's venv
is never changed.

**What runs from it.** At every start, `startup.sh`, as the runtime user, makes the
node venv if it is missing and repairs it if an interrupted start left it half
made: it rewrites the `.pth` file and the wrappers below whenever they differ, and
keeps the packages. It then checks that the venv's Python runs and sees the
image's packages, and starts ComfyUI with it. Manager installs dependencies with
`sys.executable -m pip`, so they land in it.

**It never stops ComfyUI from starting.** If the node venv can't be made or used,
for example because the runtime UID can't write it, or because Manager's `use_uv`
can't be set to `False` (below), startup logs a `WARNING` and
runs ComfyUI from the image's venv, as 6.0.0 did. What custom nodes install is then
lost on a recreate again, until you fix the cause and restart.

**In a `docker exec` session.** Its `bin/` is first on the image's `PATH`, and holds
`python`, plus `pip`, `pip3` and `cm-cli` wrappers that run from it, so a session
installs into it too:

```bash
docker exec -u "$PUID:$PGID" comfyui cm-cli install <registry id>@<version> --user-directory /app/user/__manager
docker exec -u "$PUID:$PGID" comfyui pip install <package>
```

- The `cm-cli` wrapper sets `COMFYUI_PATH=/app/ComfyUI` unless you set it. Pass
  `--user-directory /app/user/__manager` so it reads the same `config.ini` as the
  Manager inside ComfyUI.
- Restart ComfyUI afterwards to load a new pack.
- Run the session as the runtime user, not root, or the files are root-owned.
- **Don't use uv.** uv doesn't follow the `.pth` file, so `uv pip install` would
  reinstall the image's packages, torch included, into the node venv, or into
  `/app/.venv` in a session. The node venv's `uv` wrapper refuses, with exit code 2
  and a message, the `uv pip` commands that change packages. It fails closed: any
  `install`, `sync` or `uninstall` argument after a `pip` argument is refused,
  wherever options and their values sit, so `uv -q pip install` and
  `uv --python-fetch automatic pip install` are refused too. Every other command,
  `uv pip freeze` and `uv pip list` included, passes through.
  `python -m uv` from the node venv reaches the same wrapper, because uv's
  launcher looks in the venv's `bin/` first.
- `/app/.venv/bin/pip` and `/app/.venv/bin/cm-cli` still install into the image's
  venv, in the container layer, and those installs are lost on a recreate.

**Manager uses pip, not uv.** For the same reason, while ComfyUI runs from the node
venv, startup sets `use_uv = False` and `use_unified_resolver = False` in
`/app/user/__manager/config.ini` at every start, and logs each change it makes. It
writes no other key there, and leaves the file alone when both are already `False`,
so your other settings stay. If the file doesn't exist yet, startup creates it with
those two keys and `file_logging = True`, Manager's default, because Manager reads a
missing boolean as false; Manager then uses that file instead of writing its own
defaults. Setting `use_uv = True` again has no lasting effect while the node venv is
on. If the file can't be parsed or written, startup logs a `WARNING` and leaves it as
it is. It then checks what Manager will actually use, and runs ComfyUI from the node
venv only if:

- `/app/user/__manager` is writable by the runtime UID, or already holds Manager's
  subdirectories (`snapshots`, `startup-scripts`, `cache`, `batch_history`).
  Otherwise Manager 4.2.2 can't set up its directory there, reads its config from
  its package directory instead, and that defaults to uv; and
- `use_uv` and `use_unified_resolver` both read back as `False` there.

Anything else, including a file that is missing or can't be parsed, which Manager
treats as uv, makes ComfyUI run from the image's venv for that start, with a
`WARNING`, as described above.

**Identity.** Both startup paths make the node venv as the runtime UID: under a root
start, after the drop to `PUID:PGID`; under a non-root start, as that UID. The
`user` volume must be writable by that UID, which the contract already requires. If
the runtime UID changes later, the node venv still loads, but the new UID can't
install into it until you `chown -R` it, as with the rest of the volume.

**Size, and its own volume.** Packs can pull in large dependencies, and those now
count against the `user` volume, beside `comfyui.db`; a full volume can stop the
database from being written. Size it for the packs you install. To keep the node
venv on other storage, mount a volume at `/app/user/__node_venv` itself, made
writable by the runtime UID before the first start: `chown PUID:PGID` on the host
side under Compose, or `fsGroup` under Kubernetes. The entrypoint doesn't `chown`
it, and a fresh named Docker volume is `root:root`, so without that step startup
can't make the node venv and runs ComfyUI from the image's venv, with a `WARNING`.

### Shadowed image packages

A package in the node venv wins over the image's copy of it. That is how a pack gets
a version the image doesn't have, but it can also replace something ComfyUI itself
depends on:

- **Manager can put a whole torch there.** When an install changes the torch,
  torchvision or torchaudio version Python sees, Manager reinstalls the previous
  versions with pip (`torch_rollback`). From the node venv, that reinstall lands in
  the node venv: gigabytes on the `user` volume, shadowing the image's torch even
  when the versions match.
- **On ROCm and XPU,** a pack whose dependencies require a torch version the
  image's doesn't satisfy makes pip fetch torch from PyPI, which is a CUDA build.
  Manager drops `torch` lines from a pack's own `requirements.txt`, but not a
  dependency's requirement on it. It shadows the
  image's ROCm or XPU torch, and ComfyUI loses the GPU. On the CPU image the same
  thing pulls a CUDA torch of several GB.

At every start, startup lists each package the node venv shadows, with both
versions, in a `WARNING`, and adds a second `WARNING` when the list includes torch,
torchvision, torchaudio, numpy or a `comfyui-*` package. To go back to the image's
copies:

```bash
docker exec -u "$PUID:$PGID" comfyui pip uninstall -y torch torchvision torchaudio
docker restart comfyui
```

Run from the node venv, `pip uninstall` removes only the node venv's copy, and
refuses to touch `/app/.venv`. Name whatever the `WARNING` listed. A pack that
needed that version may then fail to import.

### When the Image Changes

The node venv records the image's ComfyUI version and its torch and numpy versions.
When they change, startup logs a `NOTICE` and carries on: a pack's compiled
dependency, built against the old torch or numpy, can then fail to import, and a
package the node venv pinned can shadow a newer one the image now ships. If a pack
fails to import after an image update:

1. stop the container;
2. delete `/app/user/__node_venv` (on the host, `<COMFY_USER_PATH>/__node_venv`);
3. start the container, which makes it again, empty;
4. `docker exec -u "$PUID:$PGID" comfyui cm-cli restore-dependencies --user-directory /app/user/__manager`,
   which reinstalls every installed pack's requirements and runs its `install.py`;
5. restart ComfyUI.

When the image's Python version changes, startup does steps 2 and 3 itself, with a
`WARNING`, because packages built for another Python can't load. Steps 4 and 5 are
still yours.

**Upgrading from 6.0.0.** Packs installed on 6.0.0 had their dependencies in the old
container's layer, so after the upgrade they show `IMPORT FAILED` in the log. Run
steps 4 and 5 once; from then on their dependencies are in the node venv.

**Turning it off.** `COMFY_ENABLE_NODE_VENV=false` runs ComfyUI from the image's
venv, as before, and leaves `config.ini` alone. A node venv that already exists stays
first on `PATH` for `docker exec` sessions, so delete it too.

## Manager Security

ComfyUI has no authentication, and Manager, enabled by default
(`COMFY_ENABLE_MANAGER`), adds routes that change the instance.

**Manager's reboot route is open to anyone who can reach port 8188.** At Manager's
default `security_level`, `normal`, any client can `POST /v2/manager/reboot` to
restart ComfyUI. The same level lets any client uninstall a pack, remove a snapshot,
and change Manager's channel URL, update policy and database mode. Keep the port on a
private network or behind an authenticating proxy.

**What `COMFY_MANAGER_SECURITY_LEVEL` does on these images.** It writes Manager's
`security_level` at every start; unset, the file's own value stands. With Manager
4.2.2, on these images, which always listen on a non-loopback address and leave
Manager's network mode at its default:

| Value | Effect |
|-------|--------|
| `strong` | Refuses everything above: the reboot route answers `403`, and uninstalls, snapshot removal and the setting changes are refused. **The only value that changes anything here** |
| `normal` | Manager's default: the routes above are open |
| `normal-`, `weak` | The same as `normal` on these images. Their extra permissions apply only to a loopback listener or a different network mode |

**Installs over HTTP stay refused at every level.** Manager's default UI refuses
installs, update-all, fixes, snapshot restores and a ComfyUI version switch while
ComfyUI listens on a non-loopback address, unless its network mode is
`personal_cloud`, which the image doesn't set. The legacy UI's git-URL and pip
installs have their own gate, Manager's `allow_git_url_install` and
`allow_pip_install`, independent of `security_level`, and also need a loopback
listener or `personal_cloud`. Installing over the network is tracked in
[#125](https://github.com/pixeloven/ComfyUI-Docker/issues/125). `cm-cli` in a
`docker exec` session is gated by none of this.

## Developing a Node Pack

You can use the image as the runtime for a custom node pack you're writing: mount
the pack's source into the container, edit it on the host, and restart ComfyUI to
load your changes. This section covers what the image does with a mounted pack.
How to write a node is upstream's subject, in
[ComfyUI's custom node docs](https://docs.comfy.org/custom-nodes/overview).

Checked on ComfyUI v0.38.0 with Manager 4.2.2, on `core:cpu`.

### Mounting the Source

Bind-mount the pack's directory at **`/app/custom_nodes/<pack>`**, inside the
`custom_nodes` volume. ComfyUI loads it like any installed pack.
[`examples/core-cpu/docker-compose.dev-pack.yml`](../../examples/core-cpu/docker-compose.dev-pack.yml)
is a Compose override that does this for the CPU example:

```bash
cd examples/core-cpu   # set `source` and `target` in docker-compose.dev-pack.yml first
docker compose -f docker-compose.yml -f docker-compose.dev-pack.yml up -d
```

The override also sets `stop_signal: SIGINT`, so a `docker restart` doesn't wait
out the stop timeout, and a running prompt is abandoned; see
[Stopping](#stopping).

With `docker run`, add `-v /path/to/my-pack:/app/custom_nodes/my-pack` beside the
`custom_nodes` volume's own mount. Mount it at `/app/custom_nodes`, never at
`/app/ComfyUI/custom_nodes`, for the reasons in [Volumes](#volumes).

Docker creates the mount point as an empty, root-owned directory in the
`custom_nodes` volume, and it stays there after you stop mounting the pack, so
ComfyUI then logs `IMPORT FAILED` for it at every start. Remove it once you're
done: `rmdir data/custom_nodes/<pack>` in the example.

**File ownership.** The source keeps its owner on the host. On a root start, the
entrypoint's `chown` stops at the volume roots (see
[Started as Root](#started-as-root)), and the mounted pack is below one, so the
files stay yours whatever `PUID` is. On a non-root start nothing is `chown`ed at
all. Either way, ComfyUI only needs to read the source, so it loads under any
runtime UID as long as its directories are world-readable and searchable and its
files world-readable (`0755` and `0644`, as git checks them out). The image sets
`PYTHONDONTWRITEBYTECODE=1`, so no `__pycache__` appears in your checkout. If your
pack writes into its own directory at runtime, run the container as your own UID:
`PUID`/`PGID` set to your `id -u`/`id -g` on a root start, or that UID on a
non-root start.

**Dependencies.** Nothing installs a mounted pack's `requirements.txt`. Install
it into the [node venv](#the-node-venv) from a session as the runtime user, then
restart:

```bash
docker exec -u "${PUID:?}:${PGID:?}" comfyui-core-cpu pip install -r /app/custom_nodes/my-pack/requirements.txt
```

`PUID` and `PGID` are read from your shell here, not from the example's `.env`, so
set them to the same values first. With them unset, `-u ":"` would run the session
as root and leave root-owned files in the node venv; `${PUID:?}` stops the command
instead.

### Restarting

ComfyUI has no hot reload for Python. What a change needs:

| You changed | To load it |
|-------------|------------|
| Any Python in the pack: a node's class, `INPUT_TYPES`, `NODE_CLASS_MAPPINGS` | Restart ComfyUI |
| A file in a web directory ComfyUI already serves, or a new file there | Reload the page. ComfyUI serves `/extensions/<pack>/…` from disk with `Cache-Control: no-store`, and lists new `.js` files on the next page load |
| A new pack, a `WEB_DIRECTORY` that is new or moved, or a pack that failed to import at the last start | Restart ComfyUI. Web directories are registered only at startup; until then their files answer `404` |

Two ways to restart:

- **Manager's reboot route**, with Manager on (`COMFY_ENABLE_MANAGER`, the
  default):

  ```bash
  curl -X POST http://localhost:8188/v2/manager/reboot
  ```

  Manager re-executes ComfyUI in place, in the same container and as the same
  UID, so the container doesn't restart. The request gets no response, because the
  process answering it is replaced: `curl` reports an empty reply. ComfyUI answered
  `/system_stats` again about 11 s later on `core:cpu`, most of it ComfyUI's own
  startup. The route answers `403` under `COMFY_MANAGER_SECURITY_LEVEL=strong` (see
  [Manager Security](#manager-security)).
- **`docker restart <container>`**, which works with Manager off too. It took about
  22 s on `core:cpu`, about 10 s of it Docker waiting out its stop timeout: the
  image doesn't stop on `SIGTERM` yet, so Docker kills it
  ([#120](https://github.com/pixeloven/ComfyUI-Docker/issues/120)).

### Where Import Errors Appear

A pack that fails to import doesn't stop ComfyUI. Its classes are missing from
`/object_info`, and the error is only logged: a traceback, then
`Cannot import /app/custom_nodes/<pack> module for custom nodes: <error>`, and the
pack marked `(IMPORT FAILED)` in the `Import times for custom nodes` list. No stable
HTTP route reports it. The log is in three places:

- **`docker logs <container>`**, the container's output.
- **`GET /internal/logs`**: ComfyUI's last 300 log entries, as one JSON string
  (`/internal/logs/raw` returns an object,
  `{"entries": [{"t", "m"}, …], "size": {"cols", "rows"}}`). ComfyUI documents every
  `/internal/` route as for its frontend's use only and not to be depended on, so
  read it by hand rather than building on it.
- **Manager's log file, `/app/user/comfyui_<COMFY_PORT>.log`**, on the `user`
  volume, with Manager on. Each start, a Manager reboot included, moves the previous
  file to `comfyui_<COMFY_PORT>.prev.log`, and that one to `.prev2.log`. Manager
  prints `** Log path: /app/user/comfyui.log` at start, without the port; the file
  it writes has the port in its name.

Manager's `POST /v2/customnode/import_fail_info` doesn't know a hand-mounted pack:
it looks packs up by registry ID or repository URL, and answers `400` with an empty
body for a pack it didn't install.

To check that a node loaded, ask for its class:
`GET /object_info/<class>` returns `{}` when the class isn't loaded.

CI checks the mount itself. `tests/smoke/run.sh`, which the `smoke-cpu` job and
`make smoke` run, mounts a one-node V1 pack at `/app/custom_nodes/smoke_dev_pack`
from a source owned by another UID, starts the image as root with `PUID`/`PGID`
`1001`, and fails unless the pack's class is in `/object_info` and the source still
has its owner.

## The `mcp` Image

`ghcr.io/pixeloven/comfyui/mcp` is an MCP server for agents, separate from the
ComfyUI images and talking to ComfyUI over HTTP. Since 5.0.0 it is
[comfyrelay](../../services/comfyrelay/README.md), this repository's own server;
before that it packaged artokun/comfyui-mcp. Run one beside each ComfyUI, as a
sidecar. Its README explains every setting and tool.

| Contract | Value |
|----------|-------|
| Endpoint | Streamable HTTP at `/mcp` on port `9000` (`MCP_PORT`), on `MCP_HOST` (default `0.0.0.0`, all interfaces) |
| Token | `COMFYUI_MCP_HTTP_TOKEN` is **required, and at least 32 characters**. Without one, or with a shorter one, the container exits 2 at start and says why (`openssl rand -hex 32` makes one). Clients send `Authorization: Bearer <token>` or `X-API-Key: <token>`. A request passes if either header carries the token, so a gateway can send its own Bearer and this token as `X-API-Key`. Anything else gets `401` |
| ComfyUI | `COMFYUI_URL`, default `http://localhost:8188`, as reachable from the `mcp` container. The server contacts nothing else |
| Output links | Optional `COMFYUI_PUBLIC_URL` is a client-accessible HTTP(S) ComfyUI base, including an optional proxy path prefix. `workflow_outputs` adds nullable `view_url` alongside the existing `view_path`; unset or blank yields null and never exposes the internal URL. Invalid hosts/ports, credentials, queries, fragments, literal `@`, whitespace, controls and backslashes are refused at startup (exit 2, value not echoed). The operator owns routing and access: links grant no access, carry no MCP token and are never fetched by the relay. Inline retrieval remains capped at 5,000,000 bytes; both known-size and streamed `output_too_large` errors include `view_path` and `view_url` |
| Tools | Chosen by `COMFYUI_MCP_PROFILES` from `read`, `run` and `manage`, default `read,run`. The tool names are part of this contract (below). `develop` is refused: the container exits 2 at start and says so |
| Large requests | At most `COMFYUI_MCP_MAX_LARGE_REQUESTS` (default `2`) `POST` requests with a body over 1 MiB are handled at once. Every chunked `POST` counts as large, whatever its `Content-Length`. No other method is limited: a `GET` opens the standing event stream, whatever it carries. One more waits up to 5 seconds, then gets `503` with `Retry-After` and a JSON error with `"retryable": true`. While it holds a slot, a large request's body must keep arriving, so a stalled client can't hold one: no data for 30 seconds gets `408` (`request_timeout`, retryable), and a body not complete within 120 seconds of taking the slot gets `408` marked not retryable, since that is a minimum throughput (about 1 Mbit/s for a maximum-size upload) and a retry over the same link would fail again. Either way the slot is released |
| Memory | 256 MiB at the default large-request limit, with up to three clients that upload large files. It idles at about 90 MB and one maximum-size upload peaks at about 150 MB. Each MCP session keeps its last request (about 25 MB after a maximum-size upload) until its next message or 30 idle minutes |
| User | `1000:1000` by default (numeric `USER`), and any UID works. It writes nothing, so a read-only root filesystem works |
| Stopping | `SIGTERM` stops the server at once. `tini` is PID 1 and passes the signal on |

These are the promises. Breaking one is a major version, by the same rule as the
rest of this page. So is renaming or removing a tool, or moving one to another
profile: the tool names are versioned with the image.

The other variables (`COMFYUI_MCP_INSTANCE_ID`, `COMFYUI_MCP_MAX_JOBS` and
`COMFYUI_MCP_DOCS`) are documented in the README, with the memory measurements. Under
Kubernetes, set `resources.limits.memory: 256Mi` on the container, as the opt-in sidecar in
[`examples/kubernetes/with-mcp/`](../../examples/kubernetes/README.md#adding-the-mcp-sidecar-opt-in) does, and raise it with
`COMFYUI_MCP_MAX_LARGE_REQUESTS` or with the number of clients that upload large files.

## The `mcp-convert` Image

`ghcr.io/pixeloven/comfyui/mcp-convert` is the same server with a headless
Chromium added, so it can convert the editor's UI-format workflows into the API
format `/prompt` takes ([#167](https://github.com/pixeloven/ComfyUI-Docker/issues/167)).
It runs the instance's own frontend, so a conversion is what the editor's
Export (API) would write. It is built from the same Dockerfile with
`RELAY_CONVERT=1` and published with the same tags as `mcp`. Opting in means
changing the image; the `mcp` image has no browser.

Everything in [The `mcp` Image](#the-mcp-image) holds for it too, except
where this table says otherwise.

| Contract | Value |
|----------|-------|
| Conversion | On (`COMFYUI_MCP_CONVERT=1`, set by the image). `0` turns it off, and the server then answers as the `mcp` image does. `server_info.capabilities.conversion` reports the state (`ready`, `running`, `backing_off`, `unavailable`, `stopped` or `off`), when it can't convert why, and once a tab has loaded the frontend, its `frontend_version` |
| Frontend | The conversion is whatever the frontend `COMFYUI_URL` serves would export. Each image version is tested against the ComfyUI `COMFYUI_VERSION` pins, and its frontend (1.53.6 for v0.38.0); the lockdown's path allowlist was derived on that frontend. Against another ComfyUI or frontend (`core:nightly`, or a custom `--front-end-version`) it is untested: a frontend that needs a path the allowlist lacks fails to load, as `conversion_unavailable` |
| Multi-user | Not supported. On a ComfyUI started with `--multi-user` the frontend waits for someone to choose a user, so every conversion fails with `conversion_unavailable` after about 30 seconds |
| Tools | The same tool names and profiles. `template_get` takes `format: "api"`; `workflow_validate` and `workflow_run` also take a UI-format graph, convert it first and report `converted_from_ui`; `workflow_validate` returns the converted graph, up to 80,000 characters. A conversion that can't run fails with `conversion_unavailable` (retryable when it may work later: the browser didn't start, the frontend didn't load, a tab or the browser went away, every tab stayed busy), and one the frontend rejects with `conversion_failed`; there is no fallback converter. `workflow_run` checks a UI graph for partner-API nodes before it converts it |
| Writable paths | `/tmp`, which must be writable: the browser keeps its profile there and the Playwright driver its scratch files (a few hundred KB). A read-only root filesystem works with a tmpfs on `/tmp`. Without one, every conversion fails with `conversion_unavailable` |
| User | `1000:1000` by default, and any UID works, as for `mcp` |
| Tabs | `COMFYUI_MCP_CONVERT_PAGES` (default `2`, at most `8`) frontend tabs convert at once; more conversions wait for one, up to 60 seconds. Each tab costs about 265 MB |
| Memory | About 100 MB until the first conversion starts the browser. Then, with the default 2 tabs, about 1.1 GB idle, 1.5 GB with 6 conversions at once, and up to 2.4 GB over a long run of conversions (the container's cgroup peaked at 2.32 GB, with a real input file for every template input). Input files don't add to that: graphs whose input is a 410 MB video peaked at 1.97 GB. Set a limit of at least 3 GiB with 2 tabs, and about 265 MB more for each extra tab |
| Latency | The first conversion starts the browser and takes about 5 seconds. After that every conversion waits at least 0.3 seconds for the tab's network to go quiet before it exports (a median of about 0.37 seconds for a template with no loaders), and about 0.55 seconds when the graph's input files exist, since the relay lets their previews load first (a loaded video preview changes what the export holds), for at most 10 seconds; measured on 8 CPUs. On a host starved of CPU a preview can take longer, and the export then lacks a UI-only input such as `video-preview`, which ComfyUI ignores |
| Size | About 304 MB to pull and 1.18 GB on disk, against 63 MB and 280 MB for `mcp`. Measured on main's `mcp-convert:ad8420ac`: the compressed layers in its registry manifest, and `docker image ls` DISK USAGE on Docker 29's containerd image store, which keeps the compressed layers beside the unpacked ones |
| Stopping | `SIGTERM` closes the browser along with the server, within the `mcp` image's budget |

**The lockdown.** The browser has no network: every connection it makes,
to ComfyUI or anywhere else, goes to a proxy that doesn't exist, and every
name it looks up resolves to nothing. What reaches ComfyUI is sent by the relay
itself: a `GET`, with no body, for a path the frontend needs, which the relay's
README lists. Any other method, host or path the page asks for is refused, fail
closed. So the relay **sends ComfyUI no write** while it converts: no `POST`,
no prompt, no `extra_data`, no credentials. That is tested against a stand-in
ComfyUI that records every request it receives, while a page script tries
every channel out it can (workers, shared workers, websockets, speculation
rules, beacons, iframes, popups, WebRTC, WebTransport), each first shown to get
out of a plain browser. The frontend's own settings writes, which it makes as
it starts, are answered inside the relay and never sent. A graph whose
frontend code uploads while it is exported (Load3D does) always fails with
`conversion_failed`. A `COMFYUI_URL` that carries credentials is refused for
conversion (the server itself still uses it).

**What stays reachable, and the browser's posture.** The `GET` routes on the
allowlist, as ComfyUI implements them, which on a bare ComfyUI v0.38.0 only
read. Query strings aren't checked, so a parameter such as `/api/userdata`'s
`dir` is left to ComfyUI's own path checks. An input file for a preview
(`/api/view`) is read in ranges of at most 4 MiB, so an input video of any size
stays cheap, and every other answer is capped at 32 MiB. Under `/extensions/` any `GET` a
custom node registers there is reachable, and custom-node JavaScript loads and
runs in the page, because a custom node's widgets can change what the export
writes; it runs under the same lockdown. Chromium runs without its sandbox
(`--no-sandbox`): Docker's default seccomp profile together with
`no-new-privileges` leaves it none it can use. A renderer compromised by a
page would run as the relay's UID, in the container that holds
`COMFYUI_MCP_HTTP_TOKEN`; the browser's own environment doesn't carry it. If that
is not acceptable for a deployment, run
`mcp` instead. Chromium's security fixes reach the image when its Playwright
pin moves, which is meant to follow each Playwright release, about monthly.

## The `comfyctl` Image

`ghcr.io/pixeloven/comfyui/comfyctl` is the `comfyctl` CLI as an image, for
materialising a lock's models into a volume: as a Job, an init container, or the
examples' opt-in `fetch` service. It talks to no ComfyUI. It replaced the
`fetch` image in 6.0.0
([#197](https://github.com/pixeloven/ComfyUI-Docker/issues/197)).
[`services/comfyctl/FETCH.md`](../../services/comfyctl/FETCH.md) documents the
`fetch` group.

| Contract | Value |
|----------|-------|
| Entrypoint | `comfyctl`, with no default command. Arguments name the group and the verb: `<image> fetch fetch /lock.yaml /app --apply`, `<image> fetch check /config/comfy.yaml /config/comfy-lock.yaml`. The `fetch` image's entrypoint was `comfyctl fetch fetch` |
| Exit codes | `0` did what was asked, `1` a real failure (a source didn't resolve, a hash didn't match, a manifest and its lock disagree), `2` a bad request (a missing file, an unknown profile, incompatible flags, or arguments for the old entrypoint) |
| Credentials | Read from the environment variables the lock's `auth:` map names, by host (the examples pass `HF_TOKEN` and `CIVITAI_TOKEN`). Never from the image or the lock |
| User | `USER 1000`, with no group, so it runs as `1000:0`. Any UID works: the image itself needs nothing writable. `fetch fetch --apply` needs write access to the destination volume, where it writes each file beside its target (`<name>.fetch-tmp`) and renames it into place |
| Read-only root | Works for every verb. `check`, `build`, `facts`, `fetch` and `resolve` write only to the paths you mount: `fetch` and `resolve -O` write a temporary file beside their target, then rename it. `resolve` hashes a download as it streams, so it needs no temp directory (since 6.0.0) |
| Tags | `<sha8>` and `latest` from a push to `main`, `X.Y.Z` and `X.Y` from a release. No runtime prefix and no `nightly`. Pin a digest; the release's `IMAGE-DIGESTS.txt` lists it. `comfyctl:cache` is the build cache, rewritten by every publishing build: never pull or pin it |
| Labels | `org.opencontainers.image.source` (this repository), `org.opencontainers.image.description` and `org.opencontainers.image.licenses` (`MIT`). There is no `org.opencontainers.image.version`: on the other images it states the ComfyUI inside, and this one has none |

These are promises by the same rule as the rest of this page: breaking one is
a major version.

## What Counts as a Breaking Change

[`VERSIONING.md` → *What counts as major*](../../VERSIONING.md#what-counts-as-major)
is the rule. On this page, that covers:

- Renaming or removing a variable in [Read by the Container](#read-by-the-container),
  changing its default, or giving it a new meaning. The same goes for a
  `COMFY_*_PATH` or other Compose variable an example documents.
- Moving or removing a path in [Volumes](#volumes), or the database location.
- Changing the default port, or how `COMFY_PORT` sets it.
- Breaking a promise in [What Startup Promises](#what-startup-promises): a UID or
  GID in range that used to run no longer does, `PUID`/`PGID` stop being honoured
  on a root start, or the runtime UID loses its passwd entry, the promised `HOME`,
  or write access to the volume roots.

The mechanisms behind those promises are not frozen. The validation code, the
`chown`, `gosu`, and how an arbitrary UID gets its entry can all change, as long as
the outcomes hold.

`/system_stats` is upstream's route. If it ever changed, the change would arrive
through a `COMFYUI_VERSION` bump, and that bump would then break this contract.

Adding is never major. A new variable, volume, or image is a minor version. The
repository owner confirms how each change is classified.

## Known Defects (Not Contract)

This is current behaviour that nobody should rely on. Fixing any of these is **not**
a major change.

- [#115](https://github.com/pixeloven/ComfyUI-Docker/issues/115): the caches under `/app/.cache` are lost when the container is recreated. Custom-node dependencies are not, with the [node venv](#the-node-venv) on.

---

**See Also:**
- [Running Containers](running.md) - Compose operations and `.env` configuration
- [Data Management](data.md) - Directory structure and permissions
- [Performance Tuning](performance.md) - What to put in `CLI_ARGS`
- [Kubernetes example](../../examples/kubernetes/README.md) - A minimal Deployment that takes the non-root path
