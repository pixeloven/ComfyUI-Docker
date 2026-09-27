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
| `COMFYUI_MCP_HTTP_TOKEN` | *(unset, required)* | The token clients send, as `Authorization: Bearer <token>` or `X-API-Key: <token>`. Without it the server logs `Refusing to start` and exits 2. It must be visible ASCII (no spaces, line breaks or other characters a header can't carry); anything else also exits 2, and the value is never printed. |
| `COMFYUI_URL` | `http://localhost:8188` | Where ComfyUI answers, from this container. It must be an `http://` or `https://` URL with a host, or the server exits 2 at startup. A `user:password@` in it is sent to ComfyUI but never shown: logs and errors print `***@`. Percent-encode any `/`, `?`, `#` or `@` in the credentials (`/` is `%2F`): unencoded, they end the host part early, and the server refuses the URL. |
| `MCP_HOST` / `MCP_PORT` | `0.0.0.0` / `9000` | The listen address. The path is always `/mcp`. |
| `COMFYUI_MCP_PROFILES` | `read,run` | The capability profiles to enable (below) |
| `COMFYUI_MCP_INSTANCE_ID` | the hostname | How `server_info` names this sidecar. In a container the hostname is the container ID or pod name, which can change when it's recreated, so set this when a gateway federates sidecars. `server_info` reports where the ID came from (`instance_id_source`: `env` or `hostname`), and startup logs a warning when it's the hostname. |
| `COMFYUI_MCP_MAX_JOBS` | `16` | How many jobs may be in flight at once. A submission past it is refused with `too_many_jobs`. It's retryable, unless every slot is held by a job that didn't stop when cancelled, since those may never free. |
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
| `run` | Validating and running workflows | `server_info`, `job_status`, `job_cancel`, `workflow_validate`, `workflow_run`, `workflow_outputs`, `workflow_upload_input` |
| `manage` | Changing what's installed, through the manifest and lock (v2) | `server_info` |
| `develop` | Custom node development, on a sandboxed dev instance only | `server_info` |

`server_info` is in every profile. An enabled profile with nothing else logs a warning at
startup, and `server_info` lists it under `profiles.without_tools`. In this skeleton that
includes `read`, whose tools come in #132.

## Tools

Names are part of the interface: renaming or removing one is a major version. New tools take
a namespace prefix (`workflow_*`, `node_*`, `model_*`, `docs_*` or `dev_*`). `server_info` and
the `job_*` group are the cross-cutting names.

- **`server_info`** identifies the sidecar. It returns the instance ID and where it came from,
  active profiles, capabilities (tools, consent policy, jobs), and ComfyUI's version, both live
  from `/system_stats` and pinned from the image, with whether they match. It also has a
  `corpus` entry, empty until the docs corpus lands (#134). It doesn't fail when ComfyUI is
  down or answers with something unexpected; `comfyui.error` says why.
- **`job_status`** reads a long-running job by `job_id`, and changes nothing (it's annotated
  read-only). With `timeout_seconds` above 0 it waits up to that long (at most 300) for the job
  to finish; the job keeps running when a wait times out. Keep each wait under your client's
  own tool-call timeout (often about 60 seconds), and wait again rather than longer.
- **`job_cancel`** stops a job (it's annotated destructive and idempotent). It waits up to 10
  seconds for the job to unwind; a job still unwinding after that reports `cancelling`, and
  `job_status` shows it reach `cancelled`. A cancelled job ends `cancelled`, with no `result`,
  even if its work swallows the cancellation and returns something. Cancelling a finished job
  changes nothing.

Jobs live in memory, so they don't survive a restart. At most `COMFYUI_MCP_MAX_JOBS` run at
once. Workflow runs are the only jobs so far (see *Workflow tools*).

**The producer contract** (written out in `comfyrelay/jobs.py`). Code that runs as a job must:

1. Let a cancellation through, re-raising `CancelledError` within 3 seconds. That's its budget
   when the server stops, so it's the contract. `job_cancel` waits up to 10 seconds before it
   reports `cancelling`, as a margin, but a producer that needs the margin is cut off at
   shutdown. Every producer's tests call `assert_producer_honours_cancel`
   (`tests/relay_helpers.py`), which checks the 3-second budget.
2. Keep any work it hands to a thread interruptible, with a timeout or a stop flag the thread
   checks. Cancelling the await returns at once, but the thread keeps running. On SIGINT or a
   normal exit Python waits for it with no time limit (a job in a 20-second thread held a
   SIGINT stop for 20 seconds). SIGTERM isn't delayed, but it cuts the thread off wherever it
   is.

A job that overruns its cancel is logged as an error, once, and keeps its slot until it
stops. On a stop (SIGTERM, which is how `docker stop` and Kubernetes stop a container, or
SIGINT) every job is cancelled during the server's own shutdown and each wait is bounded:
about 3 seconds for the jobs and 3 for anything else, after uvicorn's 3-second graceful
shutdown. So a coroutine that never stops can't hold the server past the default 10-second
grace period. A thread that never stops can, on SIGINT (rule 2).

**Job access is per token, not per client.** The token is the only credential, so everyone who
holds it is one principal: any session can follow or cancel any job by its ID, and IDs are
random but aren't a permission. Behind a gateway that federates sidecars, the gateway holds the
token, so every consumer it lets through shares that one principal and can see and cancel each
other's jobs. If consumers must be kept apart, the gateway has to do it, for example by giving
each consumer its own sidecar.

A failed call returns `isError: true`. Its text is the SDK's `Error executing tool <name>: `
prefix, then JSON:

```json
{"error": {"code": "comfyui_unreachable", "message": "...", "retryable": true}}
```

## Workflow tools

The `run` profile's tools for ComfyUI workflows in **API format**
(`{"<node id>": {"class_type": ..., "inputs": {...}}}`, where an input is a constant or a link
`["<node id>", <output index>]`). The editor's UI-format save file is refused with directions
to export the API format. The code is `comfyrelay/tools_workflow.py`, with the checks in
`comfyrelay/workflow.py` (#132).

- **`workflow_validate`** type-checks a graph against the live `/object_info` without running
  it. It reads `/object_info` afresh on every call, so newly installed nodes and uploaded files
  count. Each problem names `node_id`, `class_type`, `input`, `expected` and `got`, and uses
  ComfyUI's own `type` and message wherever ComfyUI reports the same fault. So a MASK wired
  into an IMAGE input is `return_type_mismatch`, "Return type mismatch between linked nodes",
  as `/prompt` would say. It reports:
  - errors: `missing_node_type` (with near names), `required_input_missing`,
    `bad_linked_input`, `linked_node_missing`, `linked_output_missing`,
    `return_type_mismatch`, `invalid_input_type`, `value_smaller_than_min`,
    `value_bigger_than_max`, `value_not_in_list` (with near values), `prompt_no_outputs`,
    `invalid_workflow`;
  - warnings, which don't stop a run: `not_connected_to_output`, `unknown_input`,
    `constant_for_link`, and a file-picker COMBO (LoadImage's `image`) set to a file that
    isn't listed. ComfyUI checks that file itself on submission.

  It expands ComfyUI's dynamic V3 inputs as ComfyUI does: `images.image0` for an Autogrow,
  `resize_type.width` for a DynamicCombo's chosen option. It's stricter than ComfyUI in two
  places. One failing output fails the graph, where ComfyUI would run the outputs that pass.
  A required DynamicCombo that's left out is an error, where ComfyUI accepts it and the node
  then fails when it runs. It can't see a node's own `VALIDATE_INPUTS` or anything that fails
  only while running. Read-only.
- **`workflow_run`** runs `workflow_validate`'s check first, and refuses an invalid graph with
  those errors (`workflow_invalid`). It refuses any graph with a **partner-API node**
  (`partner_api_nodes_refused`, naming the nodes; see below). Otherwise it submits the graph
  to `/prompt` and returns `job_id` and `prompt_id` at once. When ComfyUI refuses the graph
  anyway (`workflow_rejected`), the error carries ComfyUI's own error and its per-node errors,
  also flattened into the same shape as `workflow_validate`'s. ComfyUI drops any output that
  fails its checks and runs the rest; the dropped ones come back as warnings. Follow the job
  with `job_status`. Its `progress` says where ComfyUI has the prompt: `comfyui_state` is
  `submitting`, `queued` (with `queue_position`, where 0 is next), `running` or `finished`.
  The executing node isn't reported: that needs ComfyUI's websocket, and the relay only polls
  `/queue` and `/history/<id>`, twice a second. A finished job's `result` lists the saved
  files. A failure is a structured `error`:
  - `workflow_execution_failed`: the node id and type, the exception type and message, and
    the last traceback lines;
  - `workflow_interrupted`: something other than this job stopped it;
  - `workflow_vanished`: ComfyUI lost it (another client dequeued it, or ComfyUI restarted).

  If ComfyUI stops answering, a run waits up to 60 seconds for it to come back.
- **`workflow_outputs`** lists a finished run's files: node, `kind` (images, gifs, audio,
  ...), filename, subfolder, `type` (output or temp), MIME type, and size from a `HEAD /view`
  for the first 32 files. It also lists non-file outputs such as text. Failed and cancelled
  runs are listed too, since they may have saved something. **It streams nothing unless
  asked.** `fetch=<filename>` returns that one file inline, up to **5 MiB**: an image as MCP
  image content the model can see, audio as audio content, anything else as an embedded
  resource. A larger file is refused (`output_too_large`) with its `/view` path, which a
  person or tool with direct access to ComfyUI can use. Read-only.
- **`workflow_upload_input`** puts a file into ComfyUI's input directory through
  `POST /upload/image` (`type=input`) and returns the name ComfyUI stored it under, to put in
  LoadImage's `image` input. The file arrives base64-encoded (a `data:` URL is fine), at most
  **10 MiB** decoded. The name is sanitised: directories are dropped, anything outside
  `A-Z a-z 0-9 . _ ( ) + -` and space becomes `_`, and leading dots go. A name with nothing
  left is refused. It never overwrites: a different file under a taken name is stored as
  `name (1).ext` (`renamed: true`), and the same bytes again reuse the file that's there. It
  writes nowhere else. There's no mask variant: `/upload/mask` edits the alpha of an image
  that's already there.

**Annotations.** `workflow_validate` and `workflow_outputs` are read-only. `workflow_run` isn't
read-only, since it queues work and ComfyUI writes new output files. It isn't destructive
either: it replaces or deletes nothing, and SaveImage numbers its files rather than
overwriting them. It isn't idempotent, since every call is a new run. `workflow_upload_input`
isn't read-only, since it adds a file to the input directory, and isn't destructive, since it
never overwrites. It is idempotent, because the same bytes under the same name are stored
once. All four are closed-world: they reach only `COMFYUI_URL`.

**Partner-API nodes** call paid external services with the user's Comfy.org credentials, and
v1 never runs them (#103). A node counts as one when `/object_info` gives it
`"api_node": true`, or gives it a hidden input of type `AUTH_TOKEN_COMFY_ORG` or
`API_KEY_COMFY_ORG`, which is how such a node is handed the credentials that pay. Either is
enough, and the refusal names both the node and the signal. At the pinned v0.37.0, 271 of 959
node classes have `api_node: true`. ComfyUI sets that flag from a node's `API_NODE`, and
`--disable-api-nodes` and the editor's badge use the same one. Three more
(`ByteDanceCreateImageAsset`, `ByteDanceCreateVideoAsset`, `Krea2StyleReferenceNode`) aren't
flagged but take the credentials. A custom node that spends money by some other route shows
neither signal, and can't be detected from `/object_info`.

**Cancelling.** `job_cancel` on a run first deletes its prompt from ComfyUI's queue
(`POST /queue {"delete": [id]}`), which is a no-op unless the prompt is still waiting. Then, if
`/queue` shows the prompt running, it sends `POST /interrupt {"prompt_id": id}`. It deletes
before it looks, so a prompt that starts in between is seen running. It interrupts only its
own prompt, and ComfyUI makes the same check again on its side. Each call has a 1-second
timeout and the whole unwind has 2.5 seconds, inside the producer contract's 3. ComfyUI
honours an interrupt at the next node boundary. **A stopping relay cancels its runs the same
way.** Jobs live in memory, so a run whose relay has gone could never be followed or collected.

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
