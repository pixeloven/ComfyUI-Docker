# mcp — an MCP server for ComfyUI

A hardened packaging of upstream [artokun/comfyui-mcp](https://github.com/artokun/comfyui-mcp),
the `comfyui-mcp` package on npm. This repo writes none of the server. It pins it,
sets safe defaults, and publishes it.

It's standalone on `node:22-slim` (the package requires Node 22 or later). It doesn't
depend on the ComfyUI images. It talks to ComfyUI over HTTP, and restarts ComfyUI
through ComfyUI-Manager's HTTP API. It never needs Docker access or a shell on the
ComfyUI host.

This is the **interim** default. It was chosen because it's the only server that
passed all four tasks of the Phase 1 evaluation harness against a containerized
ComfyUI ([#102](https://github.com/pixeloven/ComfyUI-Docker/issues/102),
[#124](https://github.com/pixeloven/ComfyUI-Docker/pull/124)). The long-term choice is
[#103](https://github.com/pixeloven/ComfyUI-Docker/issues/103).

| | |
|---|---|
| Image | `ghcr.io/pixeloven/comfyui/mcp` |
| Server | `comfyui-mcp` **0.52.203**, pinned by `ARTOKUN_VERSION` in `docker-bake.hcl` |
| Endpoint | streamable HTTP at `http://<host>:9000/mcp`, on all interfaces |
| Auth | **Required.** `Authorization: Bearer <token>` or `X-API-Key: <token>` |
| ComfyUI | `COMFYUI_URL` (default `http://localhost:8188`) |
| User | non-root `comfy`, UID/GID `1000` (`APP_UID` / `APP_GID` build args) |

## The pin

`ARTOKUN_VERSION` is an exact npm version. The Dockerfile refuses a tag, a range or
`latest`, so the build fails rather than taking whatever npm serves.

0.52.203 is the version the #124 harness evaluated. It's also the newest release on
npm as of this pin, so there was no reason to move. Upstream releases very often.
Before bumping it, re-check the deny list below against that version's
`src/tools/tool-surface-filter.ts`, and check that the denied tools are still absent
from `tools/list`. A renamed tool would otherwise come back unannounced.

The package's own npm dependencies are caret ranges, and it ships no lockfile. A
rebuild at the same pin can therefore resolve newer transitive packages. The pin
fixes the server's code, not every package under it.

## Hardening defaults

Each one is set with `ENV` in the image, so a deployment gets it without having to
remember it.

| Setting | Value in the image | Upstream default | Why |
|---|---|---|---|
| Auth token | none, **you must set `COMFYUI_MCP_HTTP_TOKEN`** | none | The endpoint can install and run code on ComfyUI. Without a token, the container refuses to start (see below). |
| `MCP_TRANSPORT` | `http` | `stdio` | A container needs a port. stdio only works when the client spawns the server itself. |
| `MCP_HOST` | `0.0.0.0` | `127.0.0.1` | Loopback inside a container is unreachable from outside it. This bind is also what makes the token mandatory. |
| `MCP_PORT` | `9000` | `9100` | The port this image has always served. The path is `/mcp`, which upstream fixes. |
| `COMFYUI_MCP_AUTO_UPDATE_DISABLE` | `1` | off | Otherwise the server runs `npm install comfyui-mcp@latest` on itself at startup, which defeats the pin. The install is also owned by root, so the server couldn't rewrite itself anyway. |
| `COMFYUI_MCP_PANEL_AUTOINSTALL` | `0` | on | Otherwise it installs its own sidebar custom node into ComfyUI. |
| `COMFYUI_MCP_FORCE_REMOTE` | `1` | off | Treats ComfyUI as remote even at a loopback address (see below). |
| `COMFYUI_MCP_TOOL_DENY` | `runpod*,train_*,report_issue,apps` | none | These tools call the author's services or spend money (see below). |

### A token is required

Upstream refuses to bind a non-loopback address without a token, and this image
binds `0.0.0.0`. Started without `COMFYUI_MCP_HTTP_TOKEN`, or with a blank one, the
container exits 1 and logs:

```text
[ERROR] Fatal error: Error: Refusing to start: HTTP MCP transport bound on non-loopback host 0.0.0.0 WITHOUT an auth token — the /mcp endpoint would be OPEN to anyone who can reach this host. Fix one of:
  • set COMFYUI_MCP_HTTP_TOKEN=<secret> (recommended), or
  ...
```

A request without the right token gets `401`. Generate a long random token, for
example `openssl rand -hex 32`, and pass it from your secret store, never from a
committed file. The only ways around the requirement are explicit opt-outs:
`COMFYUI_MCP_ALLOW_UNAUTH=1`, or setting `MCP_HOST=127.0.0.1` (useful only with host
networking). Don't use either on a shared network.

### Restart goes through ComfyUI-Manager

`restart_comfyui` has two paths upstream. For a **local** ComfyUI it kills the process
and relaunches it, or runs `COMFYUI_RESTART_COMMAND`. For a **remote** one it calls
Manager's reboot endpoint (`POST /v2/manager/reboot` on Manager 4) and waits for
`/system_stats`. Upstream picks the path from the address, and a loopback address
counts as local.

From inside this container, ComfyUI is never local: it's another container or
another host. Upstream's local path can't find a process to restart, and returns
`startup: not-attempted`. That happens whenever `COMFYUI_URL` is loopback, for example
under host networking, and also when the address belongs to the host itself.
`COMFYUI_MCP_FORCE_REMOTE=1` makes every target remote, so the restart always goes
through Manager.

We prefer it to the other option, a `COMFYUI_RESTART_COMMAND` that `curl`s the same
endpoint, because it needs no shell command. It also turns off upstream's
local-filesystem and process tools, which in this container would act on the MCP
container's own filesystem rather than ComfyUI's.

Verified against the `core-cpu` image with ComfyUI 0.37.0 and Manager 4.2.2: ComfyUI
re-execs in place, the container keeps running with no restart counted, and
`/system_stats` answers again within seconds. The restart needs Manager enabled
(`COMFY_ENABLE_MANAGER=true`, the default in our images).

### What's denied

`COMFYUI_MCP_TOOL_DENY` removes these from `tools/list` entirely, and from the
`call_tool` facade, so an agent never learns they exist. The pattern matches an
exact name, or a prefix ending in `*`.

| Denied | What it does | Why |
|---|---|---|
| `runpod`, `runpod_watch` | Creates, starts and drives RunPod GPU pods from the author's template | Spends money |
| `train_doctor`, `train_prepare_dataset`, `train_start` | Sets up and runs LoRA training (Docker, GPU passthrough, a venv) | Needs Docker on the MCP host, and runs long, expensive jobs |
| `report_issue` | Files a public GitHub issue through the author's intake service | Publishes to a third party |
| `apps` | Lists and runs packaged "micro-apps", and imports them from a public registry | Installs third-party content |

Everything else stays, 34 tools in all. The upstream preset `safe`
(`COMFYUI_MCP_TOOL_PRESET=safe`) is **not** used: it removes `create_workflow`
(node info and validation) and `install_custom_node`, which are what agents need to
build workflows and install nodes.

To deny more, set `COMFYUI_MCP_TOOL_DENY` yourself, and **keep the four entries
above in your value**, because it replaces the image's list. `COMFYUI_MCP_TOOL_ALLOW`
narrows the surface to exactly the tools named. A variable that's set but empty
makes the server refuse to start, rather than silently allowing everything.

One tool that stays can spend money: `list_api_nodes` runs ComfyUI's paid partner
nodes. They only run with a Comfy account API key, either configured on ComfyUI or
given to this server as `COMFY_API_KEY`. The image sets neither.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `COMFYUI_MCP_HTTP_TOKEN` | *(unset, required)* | The bearer token clients must send |
| `COMFYUI_URL` | `http://localhost:8188` | Where ComfyUI is reachable **from this container** |
| `MCP_PORT` | `9000` | The listen port |
| `MCP_HOST` | `0.0.0.0` | The listen address |
| `COMFYUI_MCP_TOOL_DENY` | `runpod*,train_*,report_issue,apps` | See *What's denied* |
| `COMFYUI_MCP_FORCE_REMOTE` | `1` | See *Restart goes through ComfyUI-Manager* |
| `COMFYUI_MCP_AUTO_UPDATE_DISABLE` | `1` | Keeps the pin |
| `COMFYUI_MCP_PANEL_AUTOINSTALL` | `0` | Keeps the sidebar node out of ComfyUI |

Upstream reads many more: see its documentation for the version you run. Server
state, such as its generations index and saved defaults, goes to
`$HOME/.comfyui-mcp` (`/app/.comfyui-mcp`) and is lost when the container is
recreated.

## Running it

Build it locally, or pull it:

```sh
docker buildx bake mcp --load
```

### Next to an example

Each example in [`examples/`](../../examples/) is its own Compose project, with
ComfyUI as the `comfyui` service on the `comfy_network` network. Add the MCP server
to it with an override file beside the example's `docker-compose.yml`, for example
`examples/core-cpu/docker-compose.override.yml`, which Compose reads automatically:

```yaml
services:
  mcp:
    image: ghcr.io/pixeloven/comfyui/mcp:latest
    init: true
    environment:
      - COMFYUI_URL=http://comfyui:8188
      - COMFYUI_MCP_HTTP_TOKEN=${COMFYUI_MCP_HTTP_TOKEN:?set COMFYUI_MCP_HTTP_TOKEN}
    ports:
      - "127.0.0.1:9000:9000"
    security_opt:
      - no-new-privileges:true
    networks:
      - comfy_network
```

```sh
export COMFYUI_MCP_HTTP_TOKEN="$(openssl rand -hex 32)"
docker compose up -d
```

`init: true` (or `docker run --init`) matters: the server doesn't handle `SIGTERM`
as PID 1, so without an init process every stop waits out the full timeout and ends
in `SIGKILL`.

Then point your MCP client at it. For Claude Code:

```sh
claude mcp add --transport http comfyui http://127.0.0.1:9000/mcp \
  --header "Authorization: Bearer $COMFYUI_MCP_HTTP_TOKEN"
```

### Plain `docker run`

```sh
docker run -d --init --name comfyui-mcp -p 127.0.0.1:9000:9000 \
  -e COMFYUI_URL=http://<comfyui-host>:8188 \
  -e COMFYUI_MCP_HTTP_TOKEN="$COMFYUI_MCP_HTTP_TOKEN" \
  ghcr.io/pixeloven/comfyui/mcp:latest
```

## Known limits

- **Node installs need #125.** ComfyUI-Manager refuses installs over HTTP when
  ComfyUI listens on a non-loopback address, and our images start it with `--listen`
  (all interfaces). So `install_custom_node` fails against a default deployment,
  including the Compose snippet above. It works when ComfyUI listens on loopback and
  the MCP container shares its network (host networking, or one Kubernetes pod), or
  when Manager's security config allows network installs (`network_mode` /
  `security_level`, such as `personal_cloud`). The image-side decision is
  [#125](https://github.com/pixeloven/ComfyUI-Docker/issues/125).
- **ComfyUI has no authentication.** The token protects this server, not ComfyUI.
  Anyone who can reach ComfyUI's port can do everything this server can, and more,
  without a token. Keep ComfyUI on a private network, behind an authenticating
  proxy, or bound to loopback, and publish only what you must. Allowing Manager's
  network installs (above) widens that to installing and running arbitrary code.
- **The deny list is a boundary against the agent, not the operator.** Whoever sets
  the container's environment can change it. Upstream says the same.
- **Advisory gates.** Apart from the deny list, what the remaining tools do is up to
  the agent and the prompts. The server doesn't ask a human before installing a
  node pack.
