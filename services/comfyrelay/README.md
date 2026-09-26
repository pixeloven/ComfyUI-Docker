# comfyrelay

The first-party MCP server for ComfyUI-Docker: one **sidecar** per ComfyUI instance,
reached by agents over streamable HTTP with a token, and reaching its ComfyUI over the
private network. The vision spec is [#103](https://github.com/pixeloven/ComfyUI-Docker/issues/103).

comfyrelay is an independent project. It isn't affiliated with or endorsed by Comfy Org.

> **Status: skeleton, not released.** This is v1.2 of #103
> ([#131](https://github.com/pixeloven/ComfyUI-Docker/issues/131)): transport, auth, capability
> profiles, consent plumbing, jobs and `server_info`. The workflow and knowledge tools arrive in
> #132 to #134. **No release ships it:** there's no comfyrelay wheel, the released `comfyctl` has
> no `relay` group, and the image isn't published. The published `mcp` image is still the
> hardened artokun server ([`../mcp`](../mcp/README.md)). comfyrelay replaces it in #136, as a
> major version.

## Running it

From the source tree, in the uv workspace:

```sh
cd services
export COMFYUI_MCP_HTTP_TOKEN="$(openssl rand -hex 32)"
uv run comfyctl relay serve --comfyui-url http://127.0.0.1:8188    # serves http://0.0.0.0:9000/mcp
uv run comfyctl relay probe                                         # checks it, no agent needed
```

Or as an image, built locally (`comfyrelay:<IMAGE_LABEL>`, never pushed):

```sh
docker buildx bake comfyrelay --load
docker run --rm -p 127.0.0.1:9000:9000 --read-only \
  -e COMFYUI_URL=http://<comfyui-host>:8188 -e COMFYUI_MCP_HTTP_TOKEN \
  comfyrelay:latest
```

The image runs as `comfy` (1000:1000), or under any UID: it writes nothing, so a read-only
root filesystem works as it is. `tini` is PID 1, so `docker stop` and a pod's `SIGTERM` stop
it at once. The only outbound connection it makes is to `COMFYUI_URL`. Its build refuses to
finish unless the server refuses to start without a token and passes `comfyctl relay probe`.

`tests/relay/run.sh` is the integration test: it boots a `core-cpu` image, runs this image
beside it, and probes it.

## Environment

The names follow the `mcp` image wherever the two overlap, so a deployment keeps its
environment when comfyrelay moves into that image.

| Variable | Default | Meaning |
|---|---|---|
| `COMFYUI_MCP_HTTP_TOKEN` | *(unset, required)* | The token clients send, as `Authorization: Bearer <token>` or `X-API-Key: <token>`. Without it the server logs `Refusing to start` and exits 2. |
| `COMFYUI_URL` | `http://localhost:8188` | Where ComfyUI answers, from this container |
| `MCP_HOST` / `MCP_PORT` | `0.0.0.0` / `9000` | The listen address. The path is always `/mcp`. |
| `COMFYUI_MCP_PROFILES` | `read,run` | The capability profiles to enable (below) |
| `COMFYUI_MCP_INSTANCE_ID` | the hostname | How `server_info` names this sidecar. In a container the hostname is the container ID or pod name. |
| `COMFYUI_VERSION` | set by the image | The ComfyUI version the image was built for, from the bake pin |

`serve` takes the same settings as flags (`--comfyui-url`, `--host`, `--port`, `--profiles`),
except the token, which it reads only from the environment so it never appears in a process
list. `-o json` turns its log lines into JSON.

## Capability profiles

Decision 6 of #103: tools register per profile, and the profile is chosen by
`COMFYUI_MCP_PROFILES`. The gate is where tools are registered (`comfyrelay/tools.py`,
`register()`). A tool outside the active profiles isn't in `tools/list`, and calling it fails
as an unknown tool.

| Profile | For | Tools in this version |
|---|---|---|
| `read` | Introspection: nodes, models, templates, docs | `server_info` |
| `run` | Validating and running workflows | `server_info`, `job` |
| `manage` | Changing what's installed, through the manifest and lock (v2) | `server_info` |
| `develop` | Custom node development, on a sandboxed dev instance only | `server_info` |

`server_info` is in every profile. An enabled profile with nothing else logs a warning at
startup, and `server_info` lists it under `profiles.without_tools`. In this skeleton that
includes `read`, whose tools come in #132.

## Tools

Names are part of the interface: renaming or removing one is a major version. New tools take
a namespace prefix (`workflow_*`, `node_*`, `model_*`, `docs_*` or `dev_*`). `server_info` and
`job` are the two cross-cutting names.

- **`server_info`** identifies the sidecar. It returns the instance ID, active profiles,
  capabilities (tools, consent policy, jobs), and ComfyUI's version, both live from
  `/system_stats` and pinned from the image, with whether they match. It also has a `corpus`
  entry, empty until the docs corpus lands (#134). It doesn't fail when ComfyUI is down;
  `comfyui.error` says why.
- **`job`** follows long-running work by `job_id`. `action` is `status`, `wait` (up to
  `timeout_seconds`, at most 300; the job keeps running when a wait times out) or `cancel`.
  Jobs live in memory, so they don't survive a restart, but any session can follow any job.
  Nothing produces jobs yet; workflow runs will (#132).

A failed call returns `isError: true`. Its text is the SDK's `Error executing tool <name>: `
prefix, then JSON:

```json
{"error": {"code": "comfyui_unreachable", "message": "...", "retryable": true}}
```

## Consent

Some actions will need a human's approval, such as installing a node pack that isn't pinned
(decision 2, from v2). Every such action goes through one path (`comfyrelay/consent.py`):

1. **The policy** grants, refuses, or says to ask. **v1 refuses everything** and asks no one.
   The refusal points the agent at editing the deployment's `comfy.yaml` and lock instead.
2. **A human is asked** through MCP elicitation, when the policy says to ask and the client
   declared the elicitation capability. That works under both the 2025 and 2026-07-28 protocol
   revisions.
3. **The fallback:** a client without elicitation is headless, so the action is refused, and
   the reason says so.

Only an explicit approval grants. Declining, cancelling, or answering no all refuse, and every
decision is logged. v2 changes the policy, not the path.

## Developing

```sh
cd services
uv run --locked pytest -q comfyrelay/tests
```

The tests fake ComfyUI with `httpx2.MockTransport`, run MCP in memory through the SDK's own
`Client` under both protocol generations, and run the HTTP transport on a real loopback port.
The SDK is `mcp` (`MCPServer`), pinned exactly in `pyproject.toml`.
