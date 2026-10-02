# Developing Custom Nodes

How to develop a ComfyUI custom node pack, backend nodes or frontend extensions,
against these images.

## The Model

**The pack's own repository is the workspace.** A compose file in it runs the
`core` image and mounts the repository into the container as the pack, at
`/app/custom_nodes/<PACK_NAME>`. You keep your own tools on the host: your editor,
`npm`, `pytest`, `ruff`. ComfyUI is something you reach over HTTP:

| To | Call |
|----|------|
| See what the pack registered | `GET /object_info` (each class has `python_module`, `custom_nodes.<PACK_NAME>` for yours) |
| Run a workflow | `POST /prompt`, then `GET /history/<prompt_id>` |
| Read why the pack didn't load | `GET /internal/logs/raw` |
| Restart ComfyUI | ComfyUI-Manager's `POST /v2/manager/reboot` |

That is all an agent working in the repository needs too: it edits files with its
own tools and calls those routes. It doesn't need the `mcp` image
([comfyrelay](../../services/comfyrelay/README.md)), which is for agents with no
shell.

[`templates/node-pack/`](../../templates/node-pack/) has the compose file and a loop
script, `dev-check.sh`, that restarts ComfyUI and reports how the pack loaded.

## Set Up a Pack Repository

Copy the template into the root of the pack's repository:

```bash
base=https://raw.githubusercontent.com/pixeloven/ComfyUI-Docker/main/templates/node-pack
for f in docker-compose.yml docker-compose.gpu.yml .env.example dev-check.sh; do
  curl -fsSLO "$base/$f"
done
chmod +x dev-check.sh
cp .env.example .env
echo .env >> .gitignore
```

> **Pin the image.** The template's default, `core:cpu-latest`, moves with every
> merge to our `main`, so the ComfyUI you test against changes under you. For
> reproducible results, set `COMFY_IMAGE` in `.env` to a release tag and its digest:
> `ghcr.io/pixeloven/comfyui/core:cpu-X.Y.Z@sha256:<digest>`
> (`docker buildx imagetools inspect <tag>` prints the digest).

**When you upgrade**, diff your copies against `templates/node-pack/` in the release
you move to: they are copied, so nothing updates them. What a pack repo may rely on
(`PACK_NAME`, the mount path `/app/custom_nodes/${PACK_NAME}`, the `COMFY_*`
variables the compose file reads, and `dev-check.sh`'s flags and exit codes) changes
only as a versioned change of this repository.

In `.env`:

- **`PACK_NAME`** is required. It is the pack's directory name inside ComfyUI, so
  its nodes report `python_module` `custom_nodes.<PACK_NAME>`. Use the repository's
  name.
- **`PUID`/`PGID`**: set them to your host user (`id -u`, `id -g`). The container
  starts as root and drops to them. Don't also set `user:` in the compose file:
  that starts it as non-root, and then `PUID`/`PGID` are ignored (see the
  [runtime contract](runtime-contract.md#startup-root-versus-non-root)).
- **`COMFY_IMAGE`**: pin it, as above. Unset, it is `core:cpu-latest`.
- **NVIDIA**: set
  `COMPOSE_FILE=docker-compose.yml:docker-compose.gpu.yml`, which makes the default
  image `core:cuda-latest` (pin a `core:cuda-X.Y.Z` with `COMFY_IMAGE`). Setting it in `.env`
  means `docker compose` and the loop script's fallback restart both use it. For
  AMD or Intel, use `core:rocm-*` or `core:xpu-*` and copy the device lines from
  [`examples/core-amd`](../../examples/core-amd/) or
  [`examples/core-intel`](../../examples/core-intel/). Nothing in CI boots a GPU
  image, so these variants are untested.

Then:

```bash
docker compose up -d
./dev-check.sh --no-restart
```

ComfyUI is on `http://127.0.0.1:8188` (`COMFY_PORT`), and on loopback only.

Models, other custom nodes, settings and outputs live on the project's named
volumes, never in the repository. Each `COMFY_*_PATH` in `.env` can point one at a
host directory instead, for example `COMFY_MODEL_PATH` at the models of another
ComfyUI. ComfyUI writes nothing into the pack: the image sets
`PYTHONDONTWRITEBYTECODE=1`.

**Loading only your pack.** Other packs on the `custom_nodes` volume load too. To
load yours alone, set
`CLI_ARGS=--disable-all-custom-nodes --whitelist-custom-nodes <PACK_NAME>` and run
`docker compose up -d`. Manager stays on: it is a package, not a custom node.

## The Loop

```bash
./dev-check.sh [--no-restart] [--no-docker-fallback] [--expect CLASS]...
               [--workflow FILE] [--timeout SECONDS]
```

1. **Restart**: Manager's `POST /v2/manager/reboot`. If Manager is off or doesn't
   answer, `docker compose restart comfyui`, unless `--no-docker-fallback` is given:
   then the loop fails instead and never runs docker. Use it where only ComfyUI's
   HTTP API is allowed, such as an agent working without Docker access.
2. **Ready**: waits for `GET /system_stats`.
3. **Load**: lists the classes whose `python_module` is `custom_nodes.<PACK_NAME>`,
   and prints the pack's `IMPORT FAILED`, `Cannot import` and `comfy_entrypoint`
   lines from `/internal/logs/raw`, with the traceback before them. It also fails
   on the V1/V3 trap (below), and on each `--expect CLASS` that your pack doesn't
   register, saying which module did if another one has that name.
4. **Web**: lists the pack's JavaScript from `GET /extensions` and fetches each file.
   A file that doesn't return 200 fails, and so does one that imports a path
   ComfyUI calls deprecated (see [Frontend Extensions](#frontend-extensions)). So
   does a pack whose declared web directory (`WEB_DIRECTORY`, or `[tool.comfy] web`)
   has JavaScript that `/extensions` doesn't list.
5. **Run** (with `--workflow`): posts the workflow, in API format, to `/prompt` and
   waits for it in `/history`. It prints the outputs, or the error and the node that
   raised it. Only the graph is sent. Keep these workflows in the repository's
   `workflows/` directory (`./dev-check.sh --workflow workflows/smoke.json`), and
   export them from ComfyUI with Export (API).

It needs bash (3.2 or later, so macOS's own works), `curl` and `jq`. It reads
`PACK_NAME` and `COMFY_PORT` from the environment, else from `.env`, and
`COMFY_URL` overrides both host and port. It exits 0 when every check passes, 1
when one fails, and 2 on a usage error.

`--expect` is how you catch the silent failures: list the classes the pack must
register, and the loop fails when one is missing.

## Restarts

ComfyUI has no hot reload: it imports a pack's Python once, at startup. Every
Python change needs a restart.

| | Manager's reboot | `docker compose restart` |
|---|---|---|
| How | ComfyUI re-executes itself inside the running container | Docker stops and starts the container |
| Cost | the startup only, about 9 s on core-cpu | about 10 s more |
| Needs | `COMFY_ENABLE_MANAGER=true` (the default) | access to Docker |
| The container | keeps its ID, `StartedAt` and logs | restarts |

The extra 10 s is [#120](https://github.com/pixeloven/ComfyUI-Docker/issues/120):
ComfyUI ignores `SIGTERM`, so Compose waits its full grace period before it kills
the container. Don't work around it with `stop_signal: SIGKILL` in the compose file;
the loop uses Manager's reboot, which doesn't stop the container at all.

Recreating the container (`docker compose up -d` after a pull or a change to
`.env`) is a restart too, and it also loses what was installed at runtime (below).

## Where the Logs Are

An import failure has no HTTP surface of its own: a pack that fails to import is
simply missing from `/object_info`. The reason is only in the logs.

- **`GET /internal/logs`** (one string) **and `/internal/logs/raw`** (a list of
  entries): ComfyUI's last 300 log entries, held in memory and emptied by every
  restart. ComfyUI says its `/internal` routes are for its own frontend and not to
  be depended on, so a ComfyUI update may change them. A long session can push the
  startup lines out of the 300, which is one more reason the loop restarts first.
- **Manager's log file**, `/app/user/comfyui_<port>.log` on the `user` volume, with
  the previous two runs beside it as `.prev.log` and `.prev2.log`. It holds
  everything ComfyUI printed since it started:
  `docker compose exec comfyui tail -n 100 /app/user/comfyui_8188.log`.
  ComfyUI's startup banner names it `comfyui.log`, but the file has the port in its
  name.
- **The container's output**: `docker compose logs comfyui`. A Manager reboot keeps
  the same container, so this runs on across restarts.

A runtime error in a node's code comes back in full from the run itself: in
`/history`, and in `/prompt`'s answer for a validation error.

## Two Silent Traps

**V1 and V3 together.** ComfyUI checks the pack's `__init__.py` for
`NODE_CLASS_MAPPINGS` first, and only when there is none does it call
`comfy_entrypoint`. A pack that keeps its V1 mappings after adding a V3 entrypoint
loads the V1 nodes, never calls the entrypoint, and logs nothing about it. The loop
fails when `__init__.py` names both.

**Two classes with one name.** Node classes are registered by name, and ComfyUI
keeps one per name without a warning. A built-in always wins, so a pack class with
a built-in's name is dropped. Between two packs, whichever loads later wins, and the
load order is the directory listing's. `/object_info` shows the winner's
`python_module`, and `--expect` fails when it isn't yours.

## Scaffolding a Pack and Converting It to V3

`comfy-cli` scaffolds a pack from the Comfy-Org template:

```bash
DO_NOT_TRACK=1 uvx comfy-cli node scaffold    # asks for the names, makes a new directory with its own git repo
```

Copy the template files into the directory it made. To check `pyproject.toml`
against the registry's rules before you publish, run this in the pack:

```bash
DO_NOT_TRACK=1 uvx comfy-cli node validate
```

`DO_NOT_TRACK=1` turns comfy-cli's telemetry off.

The scaffold generates V1 nodes: `__init__.py` imports `NODE_CLASS_MAPPINGS` from
`src/<name>/nodes.py`. To move to the V3 API (`comfy_api.latest`):

- Each node becomes a subclass of `io.ComfyNode`. Its class method `define_schema()`
  returns an `io.Schema` with `node_id` (the class name ComfyUI registers),
  `category`, `inputs` and `outputs`. Its class method `execute()` takes the inputs
  as keyword arguments and returns an `io.NodeOutput`.
- An output node sets `is_output_node=True`. It returns
  `io.NodeOutput(ui=...)`, for example `ui.PreviewText(text)`.
- One `ComfyExtension` subclass lists the nodes in `get_node_list()`, and
  `__init__.py` defines `comfy_entrypoint()`, which returns an instance of it.
- **Remove `NODE_CLASS_MAPPINGS` and `NODE_DISPLAY_NAME_MAPPINGS`** from
  `__init__.py`; the display name moves into the schema. Leaving the mappings in is
  the V1/V3 trap above. `WEB_DIRECTORY` stays.

```python
from comfy_api.latest import ComfyExtension, io


class Shout(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="Shout",
            display_name="Shout",
            category="example",
            inputs=[io.String.Input("text")],
            outputs=[io.String.Output()],
        )

    @classmethod
    def execute(cls, text):
        return io.NodeOutput(text.upper())


class ExampleExtension(ComfyExtension):
    async def get_node_list(self):
        return [Shout]


async def comfy_entrypoint():
    return ExampleExtension()
```

## Frontend Extensions

ComfyUI serves a pack's web directory straight from the mount, and `/extensions`
lists its `.js` files again on every request. A changed or new JavaScript file
needs no restart: reload the browser tab. Only a web directory that wasn't there
when ComfyUI started (a new `WEB_DIRECTORY`, or `[tool.comfy] web` in
`pyproject.toml`) needs one.

When a browser loads a file that imports `/scripts/ui*` or `/extensions/core/*`,
ComfyUI logs a `[DEPRECATION WARNING]`. That line names the imported path, not the
extension that imported it, and it is logged only once a browser loads the file. So
the loop checks the served files themselves for those imports, and prints any
deprecation warnings it finds in the log as notes. It doesn't drive a browser: an
extension that fails in the browser passes the loop.

## Dependencies

Python packages you install at runtime, with `pip` in the container or through
Manager, go into the container's own environment. Recreating the container loses
them, while the pack stays on its mount
([#115](https://github.com/pixeloven/ComfyUI-Docker/issues/115)). Manager installs a
pack's `requirements.txt` when it installs the pack, which it doesn't do for a
mounted one. Install them yourself, as your own user, then restart:

```bash
docker compose exec -u "$(id -u):$(id -g)" comfyui pip install -r /app/custom_nodes/<PACK_NAME>/requirements.txt
./dev-check.sh
```

Repeat it after every recreate. The `complete` images come with the packages common
nodes need already installed.

## Security

- **A pack's code runs unsandboxed, inside ComfyUI.** It can read and write what
  ComfyUI can: the volumes, the repository through its mount, and the network. The
  container's hardening (`no-new-privileges`, a non-root user) limits it, but it is
  not a sandbox. When an agent writes the nodes, the isolation is wherever you run
  Docker: use a machine or VM whose data you would let that code see.
- **Keep the loopback bind.** The template publishes on `127.0.0.1` only. ComfyUI
  has no authentication, and Manager's reboot route accepts a `POST` from anyone who
  can reach the port, on every published image. Exposing the port lets anyone
  restart your ComfyUI and run workflows on it
  (see [#125](https://github.com/pixeloven/ComfyUI-Docker/issues/125)).

---

**See Also:**
- [Runtime Contract](runtime-contract.md) - The env vars, volumes and startup user the template relies on
- [Running Containers](running.md) - Compose operations and `.env` configuration
- [`tests/agent-tasks/`](../../tests/agent-tasks/README.md) - T7 and T7-fix test an agent developing a pack this way
