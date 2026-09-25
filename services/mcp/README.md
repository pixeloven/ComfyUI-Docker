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
[#124](https://github.com/pixeloven/ComfyUI-Docker/pull/124)). A first-party server,
planned in [#103](https://github.com/pixeloven/ComfyUI-Docker/issues/103), is meant to
replace it in a later major version.

| | |
|---|---|
| Image | `ghcr.io/pixeloven/comfyui/mcp` |
| Server | `comfyui-mcp` **0.52.203**, pinned by `package.json` and `package-lock.json` in this directory |
| Endpoint | streamable HTTP at `http://<host>:9000/mcp`, on all interfaces |
| Auth | **Required.** `Authorization: Bearer <token>` or `X-API-Key: <token>` |
| ComfyUI | `COMFYUI_URL` (default `http://localhost:8188`) |
| User | `comfy` (1000:1000) by default; any UID works, with `HOME=/app` |
| PID 1 | `tini`, so `docker stop` and a pod's `SIGTERM` stop it at once |

## The pin

`package.json` names `comfyui-mcp` at an exact version, and `package-lock.json` fixes
every package under it, with integrity hashes. The image installs them with
`npm ci`, so a rebuild at the same commit gets the same tree. The build fails if
`package.json` names a range, a tag or `latest`, and `npm ci` fails if the lock
doesn't match `package.json`. The base image is pinned by digest.

The lock is the only pin; there's no bake argument for the version, so the two
can't disagree. To move it, run this in `services/mcp`, with the same base image,
then rebuild and re-check:

```sh
npm install --package-lock-only --ignore-scripts comfyui-mcp@<x.y.z> --save-exact
```

0.52.203 is the version the #124 harness evaluated, and the newest release on npm
as of this pin. Upstream releases very often. Before bumping it, re-check the deny
list below against that version's `dist/tools/tool-surface-filter.js`. The build's
own probe fails if a denied tool reappears in `tools/list`, but it can't know about a
new tool that ought to be denied.

Two things the install does on purpose:

- **`--ignore-scripts`.** The only install script in the tree is `cloudflared`'s,
  which downloads the newest `cloudflared` binary from GitHub, as root, at build
  time. It's only for upstream's `--tunnel`, which this image doesn't support.
  `better-sqlite3` and `sharp` ship prebuilt binaries and work without scripts.
- **Two optional dependencies are removed**: `@anthropic-ai/claude-agent-sdk*` and
  `@openai/codex*`, which bundle the Claude Code and Codex binaries (about 760 MB).
  Only upstream's panel orchestrator and the denied `train_*` tools load them.

## Hardening defaults

Each one is set with `ENV` in the image, so a deployment gets it without having to
remember it.

| Setting | Value in the image | Upstream default | Why |
|---|---|---|---|
| Auth token | none, **you must set `COMFYUI_MCP_HTTP_TOKEN`** | none | The endpoint can install and run code on ComfyUI. Without a token, the container refuses to start (see below). |
| `MCP_TRANSPORT` | `http` | `stdio` | A container needs a port. stdio only works when the client spawns the server itself. |
| `MCP_HOST` | `0.0.0.0` | `127.0.0.1` | Loopback inside a container is unreachable from outside it. This bind is also what makes the token mandatory. |
| `MCP_PORT` | `9000` | `9100` | The port this image has always served. The path is `/mcp`, which upstream fixes. |
| `COMFYUI_MCP_ENV_FILE` | `/dev/null` | `~/.comfyui-mcp/.env` | Upstream loads that dotenv into its environment at every start. An agent can write to it (see below), so the image points it at an empty file. Pass settings as real environment variables. |
| `COMFYUI_MCP_AUTO_UPDATE_DISABLE` | `1` | off | Stops the update check at startup, which otherwise runs `npm install comfyui-mcp@latest` over the server. The same update is also an action of `install_comfyui`, which ignores this setting; that tool is denied. |
| `COMFYUI_MCP_PANEL_AUTOINSTALL` | `0` | on | Otherwise it installs its own sidebar custom node into ComfyUI. |
| `COMFYUI_MCP_FORCE_REMOTE` | `1` | off | Treats ComfyUI as remote even at a loopback address (see below). |
| `COMFYUI_MCP_TOOL_DENY` | `runpod*,train_*,report_issue,apps,install_comfyui` | none | These tools spend money, call the author's services, or modify the server itself (see below). |
| `HOME` | `/app` | | Where the server keeps its state. Writable by any UID. |

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
`COMFYUI_MCP_ALLOW_UNAUTH=1`, or setting `MCP_HOST` to a loopback address
(`127.0.0.1`, `localhost`, `::1` or `::ffff:127.0.0.1`), which is useful only with
host networking. Don't use either on a shared network.

### The server's dotenv is switched off

Upstream reads `~/.comfyui-mcp/.env` when it starts, and copies every key it finds
into its own environment. The `add_path` action of `list_local_models` writes YAML
to any `config_path` the agent names, and dotenv reads YAML's `key: value` lines. An
agent can therefore plant keys such as `NODE_OPTIONS` there, and they take effect at
the next start, surviving a container restart.

`COMFYUI_MCP_ENV_FILE=/dev/null` makes upstream read an empty file, so nothing an
agent writes is ever loaded. `add_path` still works as a tool, and can still write
YAML wherever the runtime user can write. That's why you should also:

- **Never set `COMFYUI_PATH`, or mount ComfyUI's volumes** (models, custom nodes,
  output, user) into this container. With them, the file-writing tools act on the
  files ComfyUI runs.
- **Run with a read-only root filesystem**, with a tmpfs for the server's state:
  `read_only: true` plus `tmpfs: [/app, /tmp]` in Compose, or
  `readOnlyRootFilesystem: true` with `emptyDir` volumes at `/app` and `/tmp` in
  Kubernetes. Nothing an agent writes then survives a restart. The server runs
  normally that way (tested).

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

`COMFYUI_MCP_TOOL_DENY` removes these from `tools/list`, and from the `call_tool`
facade, so an agent can't call them and isn't shown them. Calling one of upstream's
older, retired tool names can still return its redirect message, which names the
current tool even when that tool is denied; the call still fails. A pattern matches
an exact name, or a prefix ending in `*`.

| Denied | What it does | Why |
|---|---|---|
| `runpod`, `runpod_watch` | Creates, starts and drives RunPod GPU pods from the author's template | Spends money |
| `train_doctor`, `train_prepare_dataset`, `train_start` | Sets up and runs LoRA training (Docker, GPU passthrough, a venv) | Needs Docker on the MCP host, and runs long, expensive jobs |
| `report_issue` | Files a public GitHub issue through the author's intake service | Publishes to a third party |
| `apps` | Lists and runs packaged "micro-apps", and imports them from a public registry | Installs third-party content |
| `install_comfyui` | Installs or updates a local ComfyUI, and updates the server itself from npm (`self_update`), ignoring `COMFYUI_MCP_AUTO_UPDATE_DISABLE` | Would replace the pinned server, and has no ComfyUI to act on here |

Everything else stays, 33 tools in all. The upstream preset `safe`
(`COMFYUI_MCP_TOOL_PRESET=safe`) is **not** used: it removes `create_workflow`
(node info and validation) and `install_custom_node`, which are what agents need to
build workflows and install nodes.

To deny more, set `COMFYUI_MCP_TOOL_DENY` yourself, and **keep the five entries
above in your value**, because it replaces the image's list.
`COMFYUI_MCP_TOOL_ALLOW` narrows the surface to exactly the tools named, plus the
three facade tools (`list_tools`, `describe_tool`, `call_tool`), which upstream never
filters; `call_tool` only reaches tools the lists allow. A variable that's set but
empty makes the server refuse to start, rather than silently allowing everything.

### What can still spend or send

- **Partner nodes spend paid credits.** `list_api_nodes` runs them directly, and
  `enqueue_workflow`, `generate_image` and `batch` run any workflow that contains
  them. They only run with a Comfy account API key: one configured on ComfyUI, given
  to this server as `COMFY_API_KEY`, or in `$HOME/.comfy-api-key`. The image sets
  none of them.
- **`upload_image` with `action:"output"` sends files off the machine**: to S3,
  Azure Blob, Hugging Face, or an HTTP `PUT` to **any URL the agent names**. The PUT
  has no guard against internal addresses, so it can reach anything this container
  can (server-side request forgery). Upstream's per-action allow list
  (`COMFYUI_MCP_TOOL_ACTION_ALLOW`) can't withhold just this action: once set, it
  applies to every action of every tool, and a complete list would have to track
  every upstream release. Restrict this container's outbound network instead, for
  example with a Kubernetes `NetworkPolicy` that allows only ComfyUI.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `COMFYUI_MCP_HTTP_TOKEN` | *(unset, required)* | The bearer token clients must send |
| `COMFYUI_URL` | `http://localhost:8188` | Where ComfyUI is reachable **from this container** |
| `MCP_PORT` | `9000` | The listen port |
| `MCP_HOST` | `0.0.0.0` | The listen address |
| `COMFYUI_MCP_TOOL_DENY` | `runpod*,train_*,report_issue,apps,install_comfyui` | See *What's denied* |
| `COMFYUI_MCP_FORCE_REMOTE` | `1` | See *Restart goes through ComfyUI-Manager* |
| `COMFYUI_MCP_ENV_FILE` | `/dev/null` | See *The server's dotenv is switched off* |
| `COMFYUI_MCP_AUTO_UPDATE_DISABLE` | `1` | Keeps the pin |
| `COMFYUI_MCP_PANEL_AUTOINSTALL` | `0` | Keeps the sidebar node out of ComfyUI |
| `COMFYUI_WORKFLOWS_DIR` | `/app/.comfyui-mcp/workflows` | Saved workflows. Each JSON file there becomes a tool |

Upstream reads many more: see its documentation for the version you run. Don't set
`COMFYUI_PATH` (see above).

The server keeps its state under `HOME` (`/app`): saved defaults and the default
workspace in `/app/.config/comfyui-mcp/`, and download records and saved workflows
in `/app/.comfyui-mcp/`. It's lost when the container is recreated; mount a volume at
`/app` if you want to keep it.

## Sessions

The endpoint is session-based, as MCP's streamable HTTP transport defines. A client
sends `initialize` first, gets an `mcp-session-id` header back, and sends that header
on every later request. Sessions live in the server's memory, so they don't survive
a restart, and with more than one replica a load balancer needs sticky sessions.
MCP clients handle this themselves.

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
    image: ghcr.io/pixeloven/comfyui/mcp:3.0.0
    environment:
      - COMFYUI_URL=http://comfyui:8188
      - COMFYUI_MCP_HTTP_TOKEN=${COMFYUI_MCP_HTTP_TOKEN:?set COMFYUI_MCP_HTTP_TOKEN}
    ports:
      - "127.0.0.1:9000:9000"
    read_only: true
    tmpfs:
      - /app
      - /tmp
    security_opt:
      - no-new-privileges:true
    networks:
      - comfy_network
```

```sh
export COMFYUI_MCP_HTTP_TOKEN="$(openssl rand -hex 32)"
docker compose up -d
```

Then point your MCP client at it. For Claude Code:

```sh
claude mcp add --transport http comfyui http://127.0.0.1:9000/mcp \
  --header "Authorization: Bearer $COMFYUI_MCP_HTTP_TOKEN"
```

### Plain `docker run`

```sh
docker run -d --name comfyui-mcp -p 127.0.0.1:9000:9000 \
  --read-only --tmpfs /app --tmpfs /tmp \
  -e COMFYUI_URL=http://<comfyui-host>:8188 \
  -e COMFYUI_MCP_HTTP_TOKEN="$COMFYUI_MCP_HTTP_TOKEN" \
  ghcr.io/pixeloven/comfyui/mcp:3.0.0
```

### Kubernetes

Any `runAsUser` works: `HOME` is `/app`, which is writable by any UID, or give it an
`emptyDir`. The image's `tini` passes the pod's `SIGTERM` on, so the server stops at
once.

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
- **Tool names follow the upstream pin.** Upstream can rename or add tools in any
  release, so prompts and allow lists that name tools need checking on each bump.
