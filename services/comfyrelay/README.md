# comfyrelay

The first-party MCP server for ComfyUI-Docker: one **sidecar** per ComfyUI instance,
reached by agents over streamable HTTP with a token, and reaching its ComfyUI over the
private network. The vision spec is [#103](https://github.com/pixeloven/ComfyUI-Docker/issues/103).

comfyrelay is an independent project. It isn't affiliated with or endorsed by Comfy Org.

**Published as `ghcr.io/pixeloven/comfyui/mcp`** since 5.0.0
([#136](https://github.com/pixeloven/ComfyUI-Docker/issues/136)), with the same tags as the
other images: `mcp:X.Y.Z` for a release, `mcp:<sha8>` and `mcp:latest` for a build of `main`.
Before 5.0.0 that image packaged artokun/comfyui-mcp; `CHANGELOG.md` → *5.0.0* has the migration
notes. comfyrelay ships only as that image and `mcp-convert`: there's no comfyrelay wheel, and
the released `comfyctl` has no `relay` group.

**`ghcr.io/pixeloven/comfyui/mcp-convert`** is the same server with a headless Chromium, so it
converts the editor's UI-format workflows to API format through ComfyUI's own frontend (#167). It
has the same tags. See *UI-to-API conversion* below.

## Running it

From the source tree, in the uv workspace:

```sh
cd services
export COMFYUI_MCP_HTTP_TOKEN="$(openssl rand -hex 32)"
uv run comfyctl relay serve --comfyui-url http://127.0.0.1:8188    # serves http://0.0.0.0:9000/mcp
uv run comfyctl relay probe --no-docs                               # checks it, no agent needed
```

Or as the image, published or built from the checkout
(`IMAGE_LABEL=local docker buildx bake mcp --load` tags it `ghcr.io/pixeloven/comfyui/mcp:local`, a
label CI never publishes, so it can't be confused with a pulled `mcp:latest`):

```sh
docker run --rm -p 127.0.0.1:9000:9000 --read-only \
  -e COMFYUI_URL=http://<comfyui-host>:8188 -e COMFYUI_MCP_HTTP_TOKEN \
  ghcr.io/pixeloven/comfyui/mcp:5.0.0
```

Next to one of the [`examples/`](../../examples/), add it with an override file beside the
example's `docker-compose.yml` (for example `examples/core-cpu/docker-compose.override.yml`,
which Compose reads automatically):

```yaml
services:
  mcp:
    image: ghcr.io/pixeloven/comfyui/mcp:5.0.0
    environment:
      - COMFYUI_URL=http://comfyui:8188
      - COMFYUI_MCP_HTTP_TOKEN=${COMFYUI_MCP_HTTP_TOKEN:?set COMFYUI_MCP_HTTP_TOKEN}
    ports:
      - "127.0.0.1:9000:9000"
    read_only: true
    mem_limit: 256m
    security_opt:
      - no-new-privileges:true
    networks:
      - comfy_network
```

```sh
export COMFYUI_MCP_HTTP_TOKEN="$(openssl rand -hex 32)"
docker compose up -d
claude mcp add --transport http comfyui http://127.0.0.1:9000/mcp \
  --header "Authorization: Bearer $COMFYUI_MCP_HTTP_TOKEN"
```

From source there's no docs index, so `docs_search` and `docs_guide` answer
`docs_unavailable` and the probe needs `--no-docs`. To build one (it fetches the docs with
`git`), then point the server at it:

```sh
uv run comfyctl relay docs build --docs-sha <COMFY_DOCS_SHA> --skills ../skills --out /tmp/docs
COMFYUI_MCP_DOCS=/tmp/docs/docs.sqlite uv run comfyctl relay serve
```

The image runs as `1000:1000` (named `comfy`; `USER` is numeric, so Kubernetes
`runAsNonRoot` accepts it), or under any UID: it writes nothing, so a read-only root
filesystem works as it is. `tini` is PID 1, so `docker stop` and a pod's `SIGTERM` stop
it at once. The only outbound connection it makes is to `COMFYUI_URL`. Its build refuses to
finish unless the server refuses to start without a token and passes `comfyctl relay probe`.

`tests/relay/run.sh` is the integration test: it boots a `core-cpu` image, runs this image
beside it, and probes it.

## Environment

`COMFYUI_MCP_HTTP_TOKEN`, `COMFYUI_URL`, `MCP_HOST` and `MCP_PORT` are the names the `mcp`
image read before 5.0.0, so a deployment keeps them.

| Variable | Default | Meaning |
|---|---|---|
| `COMFYUI_MCP_HTTP_TOKEN` | *(unset, required)* | The token clients send, as `Authorization: Bearer <token>` or `X-API-Key: <token>`. A request passes if either header carries it, so a gateway can send its own Bearer and this token as `X-API-Key`. Without it the server logs `Refusing to start` and exits 2. It must be **at least 32 characters** (generate one with `openssl rand -hex 32`), or it exits 2 with the length and that command. It must be visible ASCII (no spaces, line breaks or other characters a header can't carry); anything else also exits 2, and the value is never printed. |
| `COMFYUI_URL` | `http://localhost:8188` | Where ComfyUI answers, from this container. It must be an `http://` or `https://` URL with a host, or the server exits 2 at startup. A `user:password@` in it is sent to ComfyUI but never shown: logs and errors print `***@`. Percent-encode any `/`, `?`, `#` or `@` in the credentials (`/` is `%2F`): unencoded, they end the host part early, and the server refuses the URL. |
| `MCP_HOST` / `MCP_PORT` | `0.0.0.0` / `9000` | The listen address. The path is always `/mcp`. |
| `COMFYUI_MCP_PROFILES` | `read,run` | The capability profiles to enable (below) |
| `COMFYUI_MCP_INSTANCE_ID` | the hostname | How `server_info` names this sidecar. In a container the hostname is the container ID or pod name, which can change when it's recreated, so set this when a gateway federates sidecars. `server_info` reports where the ID came from (`instance_id_source`: `env` or `hostname`), and startup logs a warning when it's the hostname. |
| `COMFYUI_MCP_MAX_JOBS` | `16` | How many jobs may be in flight at once. A submission past it is refused with `too_many_jobs`. It's retryable, unless every slot is held by a job that didn't stop when cancelled, since those may never free. |
| `COMFYUI_MCP_MAX_LARGE_REQUESTS` | `2` | How many `POST` requests with a body over 1 MiB (in practice, `workflow_upload_input` calls) are handled at once. No other method is limited: a `GET` opens the standing event stream, whatever it carries. One more waits up to 5 seconds for a slot, then gets HTTP `503` with `Retry-After: 2` and `{"error": {"code": "server_busy", ..., "retryable": true}}`. Every chunked `POST` counts as large, whatever its `Content-Length` says. Requests under 1 MiB never wait. While it holds a slot, a large request's body must keep arriving, so a stalled client can't hold one: no data for 30 seconds gets `408` (`request_timeout`, retryable), and a body not complete within 120 seconds of taking the slot gets `408` marked not retryable, since that is a minimum throughput (about 1 Mbit/s for a maximum-size upload) and a retry over the same link would fail again. Either way the slot is released. See *Memory* below. |
| `COMFYUI_VERSION` | set by the image | The ComfyUI version the image was built for, from the bake pin |
| `COMFYUI_MCP_DOCS` | `/opt/docs/docs.sqlite` | The docs index `docs_search` and `docs_guide` read. The image builds it there; without one those tools fail with `docs_unavailable`, and `server_info.docs` says why. |
| `COMFYUI_MCP_CONVERT` | `1` in `mcp-convert`, unset elsewhere | `1` converts UI-format workflows through the instance's own frontend (see *UI-to-API conversion*). Only `mcp-convert` has the browser it needs; anything but `1` turns it off. |
| `COMFYUI_MCP_CONVERT_PAGES` | `2` | How many frontend tabs convert at once, from 1 to 8; each costs about 265 MB. More conversions wait up to 60 seconds for a tab. |

`serve` takes the same settings as flags (`--comfyui-url`, `--host`, `--port`, `--profiles`),
except the token, which it reads only from the environment so it never appears in a process
list. Once it has read its settings, `serve` removes the token, and a `COMFYUI_URL` that carries
credentials, from its own environment, so nothing it starts later (the converter's browser and its
Playwright driver) inherits them. `-o json` turns its log lines into JSON.

## Capability profiles

Decision 6 of #103: tools register per profile, and the profile is chosen by
`COMFYUI_MCP_PROFILES`. The gate is where tools are registered (`comfyrelay/tools.py`,
`register()`). A tool outside the active profiles isn't in `tools/list`, and calling it fails
as an unknown tool.

| Profile | For | Tools in this version |
|---|---|---|
| `read` | Introspection: nodes, models, templates, docs | `server_info`, `node_search`, `node_describe`, `model_list`, `template_search`, `template_get`, `docs_search`, `docs_guide` |
| `run` | Validating and running workflows | `server_info`, `job_status`, `job_cancel`, `workflow_validate`, `workflow_run`, `workflow_outputs`, `workflow_upload_input` |
| `manage` | Changing what's installed, through the manifest and lock (v2) | `server_info` |

`server_info` is in every profile. An enabled profile with nothing else logs a warning at
startup, and `server_info` lists it under `profiles.without_tools`: today that is `manage`.

`develop` is declined (#107): asking for it, alone or with other profiles, makes `serve` exit 2
with a message that it isn't available in this image. Develop custom nodes against a ComfyUI
container directly; see [#107](https://github.com/pixeloven/ComfyUI-Docker/issues/107).

## Tools

Names are part of the interface: renaming or removing one is a major version. New tools take
a namespace prefix (`workflow_*`, `node_*`, `model_*`, `docs_*` or `dev_*`). `server_info` and
the `job_*` group are the cross-cutting names.

- **`server_info`** identifies the sidecar. It returns the instance ID and where it came from,
  active profiles, capabilities (tools, consent policy, jobs), and ComfyUI's version, both live
  from `/system_stats` and pinned from the image, with whether they match. Its `docs` entry
  lists the docs built into the image: each source with its version (the docs commit, or this
  project's version for the guides), license and page count (see *Docs tools*), or
  `status: "absent"` and the reason. It doesn't fail when ComfyUI is
  down or answers with something unexpected; `comfyui.error` says why.
- **`job_status`** reads a long-running job by `job_id`, and changes nothing (it's annotated
  read-only). With `timeout_seconds` above 0 it waits up to that long (at most 300) for the job
  to finish; the job keeps running when a wait times out. Keep each wait under your client's
  own tool-call timeout (often about 60 seconds), and wait again rather than longer. A workflow
  run this server no longer holds is looked up on ComfyUI (`source: "comfyui"`; see
  *Re-attaching after a restart*).
- **`job_cancel`** stops a job (it's annotated destructive and idempotent). It waits up to 10
  seconds for the job to unwind; a job still unwinding after that reports `cancelling`, and
  `job_status` shows it reach `cancelled`. A cancelled job ends `cancelled`, with no `result`,
  even if its work swallows the cancellation and returns something. Cancelling a finished job
  changes nothing. It cancels only jobs this server holds: any other ID is refused with
  `job_not_held`, and nothing is sent to ComfyUI (see *Re-attaching after a restart*).

Jobs live in memory, so they don't survive a restart. A workflow run's `job_id` is its ComfyUI
`prompt_id`, though, so a restarted relay can still find the run on ComfyUI. At most
`COMFYUI_MCP_MAX_JOBS` run at once. Workflow runs are the only jobs so far (see *Workflow
tools*). The IDs the store makes for other jobs are 32 hex digits, which never look like a
prompt ID (a UUID with hyphens), so the two can't collide.

**The producer contract** (written out in `comfyrelay/jobs.py`). Code that runs as a job must:

1. Let a cancellation through, re-raising `CancelledError` within 3 seconds. That's its budget
   when the server stops, so it's the contract. `job_cancel` waits up to 10 seconds before it
   reports `cancelling`, as a margin, but a producer that needs the margin is cut off at
   shutdown. Every producer's tests call `assert_producer_honours_cancel`
   (`tests/relay_helpers.py`), which checks the 3-second budget. A cancel is delivered once:
   a second `job_cancel`, or a shutdown during the unwind, waits for it rather than cutting
   the cleanup short. A producer reads why it was cancelled from
   `current_job().cancel_reason`: `cancel` (`job_cancel`) or `shutdown`. At shutdown it may
   leave its outside work running instead of undoing it. A workflow run does: its prompt
   carries on in ComfyUI. Other producers undo what they started, as before. A producer that
   finds its work had already finished before the cancel took effect raises `AlreadyFinished`
   instead of re-raising: the job then ends as the work did, with its result or its error.
2. Keep any work it hands to a thread interruptible, with a timeout or a stop flag the thread
   checks. Cancelling the await returns at once, but the thread keeps running. On SIGINT or a
   normal exit Python waits for it with no time limit (a job in a 20-second thread held a
   SIGINT stop for 20 seconds). SIGTERM isn't delayed, but it cuts the thread off wherever it
   is.

A job that overruns its cancel is logged as an error, once, and keeps its slot until it
stops. On a stop (SIGTERM, which is how `docker stop` and Kubernetes stop a container, or
SIGINT) every job is cancelled, with the reason `shutdown`, during the server's own shutdown, and each wait is bounded:
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

## Introspection tools

The `read` profile (#133), in `comfyrelay/tools_introspection.py`. All five are read-only
(annotated so) and only ever send GETs to `COMFYUI_URL`. Every answer comes from the live
instance, so custom nodes and the models actually on disk are included, and nothing is
recalled from a bundled copy.

| Tool | Reads | Returns |
|---|---|---|
| **`node_search`** | `/object_info` | Node classes matching a query by class name, display name, search alias, category or description. Each hit gives its `class_type`, display name, category, a one-line summary, its custom node `pack` (absent for built-ins), and `api_node` or `deprecated` when set. Exact name matches rank first, then prefixes, then name words, category and description, so `CheckpointLoader` and `CheckpointLoaderSimple` stay apart. Within a tier, partner-API and deprecated nodes come last. A query with no letters or digits fails with `invalid_query`. |
| **`node_describe`** | `/object_info/<class>`, and the node's help page | One class's full spec: each input (required first, in the node's order) with its type, default, min, max, step, tooltip and COMBO values; hidden inputs; outputs in socket order with names and list flags; `output_node` and `api_node`. Dynamic inputs are named as a graph must name them (below). COMBO values and Autogrow names are cut to `max_options` (default 20), with a total. An unknown class fails with `unknown_node_class` and `suggestions`; `.` and `..` are never sent to ComfyUI. `help` is the node's help page, the English markdown the editor shows, fetched live where the editor fetches it (frontend 1.52): `/docs/<class>/en.md` for ComfyUI's own nodes, which ComfyUI serves from its pinned `comfyui-embedded-docs`, and a custom node pack's own `/extensions/<pack>/docs/<class>/en.md`, then `<class>.md`. At most 64 KB of it is read; a longer page is cut there, with `help_truncated: true`. It's absent when ComfyUI has none (a 404, or an HTML page in its place) or can't serve it (any other error or a timeout): the help never fails the call. `include_help: false` leaves it out, and skips those fetches. `class_types` (up to 20, instead of `class_type`) describes several classes in one call and answers `{nodes, unknown}`: `nodes` in the order asked, and each unknown class in `unknown` with `code: unknown_node_class` and its `suggestions`, without failing the call. Those suggestions need the whole `/object_info`, read within 15 s: when it can't be read, the unknown classes come back without them, and the message says why. Giving both `class_type` and `class_types`, or neither, fails with `invalid_arguments`. |
| **`model_list`** | `/models`, `/models/<folder>` | Files on disk per folder type, or for one `folder`: at most `max_files` per folder (default 50) and 400 in all, with the full `count` and `truncated`. `custom_nodes` and `download_model_base` (an `extra_model_paths.yaml` key that ComfyUI lists as a folder type, naming the whole models root) are left out. An unknown folder fails with `unknown_model_folder` and the known ones. Nothing is downloaded. |
| **`template_search`** | `/templates/index.json`, and `/templates/index.mcp.json` when ComfyUI serves it; then each match's `/templates/<name>.json` (cached), `/object_info` and `/models/<folder>` | Workflow templates for a goal, ranked by how many query words match, weighted by field (title and name; then tags, model families, and the agent index's task, model and capabilities; then descriptions, the agent index's inputs and outputs, and category) and by how rare the word is across the index. A hit the agent index lists also carries its `task`, `inputs` and `outputs` (prose, at most 4 lines of 120 characters each), `capabilities` (at most 8), `recommend` and `freshness`; those single words are cut to 40 characters. The agent index only adds to a search and never fails one: any error fetching it (a 404 or any other status, a body that isn't an index, no connection), or no answer within 5 seconds, and the search runs on `index.json` alone. `source.index` is `index.mcp.json` when the agent index added to at least one template, and `index.json` otherwise. Partner-API templates are left out unless `include_partner_api` is set: those the index marks `openSource: false`, and any match whose graph uses a partner-API node, which is known once the template and `/object_info` are read, even if a model folder it names can't be listed. `hidden_partner_api` counts both. When `/object_info` fails or times out, or the template itself can't be fetched or isn't fetched in time, a partner-API template the index doesn't flag can't be detected, so it is returned, unchecked. Every match gets the runnability check (below), and it breaks ties: among matches of as many query words, runnable ones come first, but a runnable template never outranks one that matches more of the query. With a one-word query every match ties on words matched, so runnable templates come first. `runnable_only: true` returns only runnable templates; `hidden_not_runnable` counts those it left out. A hit carries a summary of its check: `runnable`, and for each kind with something missing (`missing_nodes`, `missing_models`, `models_need_value_change`, `missing_inputs`, `api_nodes`) its `count` and `first` 3 names, each cut to 80 characters. `template_get` gives the full lists. **Checking every match is optional work and never fails a search.** A template is reported with `runnable: null` and `unchecked` (`timeout`, the error code, or `check_failed` when reading the template or checking it against ComfyUI's data fails in a way the relay doesn't expect, such as an `/object_info` entry of an odd shape; the relay logs it) when it can't be fetched (any error, or a workflow it can't read) or isn't fetched within 5 seconds, when a model folder it declares can't be listed (any status but 404) or isn't listed within another 5 seconds, or, for every match, when `/object_info` fails or doesn't answer within 15 seconds (`template_get` waits for it as long as any other read). `unchecked` on the result counts them, and `runnable_only` leaves them out. Templates are fetched best match first, at most 8 at a time across every search the relay is running. Each search takes a slot of its own before it queues for one of those 8, so only a few of its fetches wait there at once and a short search isn't queued behind every template a long one still has to read; a template another search is already fetching is waited for, not fetched again. |
| **`template_get`** | the same, for one template | Its metadata, the runnability check, and the workflow in the frontend's UI format (`include_workflow: false` leaves it out). With `format: "api"` the workflow is converted by this instance's own frontend, where the server converts (`mcp-convert`; see *UI-to-API conversion*), and `converted_from_ui` says so; elsewhere `format: "api"` fails with `conversion_unavailable`. The runnability check is always the UI graph's. A workflow over 80,000 characters as JSON, as returned, fails with `workflow_too_large` (`size`, `limit`); `include_workflow: false` still answers. An unknown name fails with `unknown_template` and `suggestions`. |

**Dynamic inputs** (ComfyUI's V3 `comfy_api/latest/_io.py`). Inside one, every input's name is
fully qualified with dots, as ComfyUI's `finalize_prefix` joins them, and a graph must use those
names as keys:

- `COMFY_DYNAMICCOMBO_V3`: each entry of `options` is `{value, inputs}`. Set the combo to
  `value`, and give that option's `inputs` under their qualified names: `resize_type` set to
  `"scale dimensions"` adds `resize_type.width`, `resize_type.height` and `resize_type.crop`.
  Nested combos add another level (`a.b.c`).
- `COMFY_AUTOGROW_V3`: `autogrow` gives the naming rule: `names` (qualified, first
  `max_options`), `names_total`, the qualified `prefix` when there is one (`images.image`, so
  `images.image0` to `images.image49`), `min` (how many of the first names are required), `max`,
  and `item`, what each one takes.
- `COMFY_MATCHTYPE_V3`: an input that takes any of `match_type.allowed_types`. An output of this
  type carries the same type as the input its `same_type_as` names.
- `COMFY_DYNAMICSLOT_V3` (unused by v0.37.0's own nodes): its type is the slot's, and
  `slot_inputs` are the inputs it adds once something is connected.

`max_options` applies at every level, so a dynamic combo lists up to that many options, each
with its own inputs. At the default of 20 the largest spec at v0.37.0
(`ViduMultiFrameVideoNode`) is about 42,000 characters as the SDK sends it.

**Where templates come from.** ComfyUI v0.37.0 pins `comfyui-workflow-templates==0.11.66` and
serves it itself: `server.py` adds `GET /templates/{path}` through
`FrontendManager.template_asset_handler()`, which maps the package's assets, and the frontend
reads `/templates/index.json` from there. The relay reads the same route, so this image doesn't
install the package. Results carry a `source` with the package version (from `/system_stats`),
its MIT license and upstream URL. The same package writes `/templates/index.mcp.json`, an index
for agents (about 525 KB at 0.11.66) with each template's task, inputs and outputs in prose,
capabilities, and a `recommend` tier drawn mostly from usage. `template_search` joins it to
`index.json` by template name. `index.json` stays the catalogue: it has the tags, the partner-API
flag, and the templates the agent index leaves out (38 of 564 at 0.11.66, among them the LLM and
Node Basics categories). `template_get` reads only `index.json`, since by then the template is
chosen and its workflow says the rest. Custom node packs' example workflows (`/workflow_templates`)
aren't searched. The example input files templates use (images, audio, video) aren't served
there.

**The runnability check** follows comfy-mcp's `local_check` pattern. It looks at the nodes
that run, top level and inside subgraphs; bypassed and muted nodes don't run, and `Note`,
`MarkdownNote`, `Reroute` and `PrimitiveNode` exist only in the frontend. A template is
`runnable` only when all of these pass:

- every node class is in `/object_info` (`missing_nodes`, each with the pack the template names
  for it, its `cnr_id`);
- every model it declares (`properties.models` on its nodes) is on disk in the declared folder
  under the name the template uses (`missing_models`, each with its folder and source URL, and
  `folder_known: false` when this ComfyUI has no such folder type). A model found only in a
  subfolder is listed in `models_need_value_change` with `found_at`: ComfyUI rejects the bare
  name (`value_not_in_list`), so the loader's value must change;
- every file its `LoadImage`, `LoadImageMask`, `LoadAudio` and `LoadVideo` nodes name is in
  ComfyUI's input directory, checked against those inputs' options in `/object_info`
  (`missing_inputs`); an input fed by a link isn't checked; and
- it uses no partner-API node (`api_nodes`). Those spend credits, and comfyrelay refuses to run
  them (#103).

`runnable: true` doesn't mean the graph validates or will finish. The check doesn't look at
links, types or other widget values, models a template names only in widget values, files other
nodes read, or whether the machine has the memory for it.

**What `template_search` caches.** What a template needs (its active node classes, the models it
declares and the files its loaders name) depends only on its file, which doesn't change within a
templates version. The relay reads each template once per `installed_templates_version` (from
`/system_stats`) and keeps at most 2,048 in memory, least recently used dropped first. The live
side is read on every search: `/object_info` and `/models/<folder>`, so a model or input file
added since shows at once. Another templates version empties the cache, and nothing is cached
when ComfyUI reports no version. The cache lives in the relay process, so restarting ComfyUI
doesn't clear it; restarting the relay does. Template files that change while
`installed_templates_version` stays the same (for example one of the package's sub-packages
upgraded on its own) leave stale requirements until the relay restarts. Against a local core-cpu at 0.11.66, a search matching about
220 templates took about 0.7 s with an empty cache and 0.2 s after, with or without
`runnable_only`.

## Workflow tools

The `run` profile's tools for ComfyUI workflows in **API format**
(`{"<node id>": {"class_type": ..., "inputs": {...}}}`, where an input is a constant or a link
`["<node id>", <output index>]`). The editor's UI-format save file, which `template_get`
returns, is refused with directions to export the API format, except by `mcp-convert`, which
converts it first (see *UI-to-API conversion*). The code is
`comfyrelay/tools_workflow.py`, with the checks in `comfyrelay/workflow.py` (#132).

- **`workflow_validate`** checks what can be known about a graph without submitting it, against
  the live `/object_info`. ComfyUI (v0.37.0) has no dry run: `/prompt` is its only complete check,
  and it queues the graph when it passes. `/object_info` can't show a node's own
  `validate_inputs` either. So **input types and values are ComfyUI's to check**, when
  `workflow_run` submits the graph: required inputs, what a link carries, COMBO choices, and
  number conversions and bounds. An earlier copy of those checks refused graphs ComfyUI
  accepts. A `CustomCombo` takes any value, though its options list is empty. A copy would
  also drift with every ComfyUI pin.

  What `workflow_validate` does check:
  - **Errors:**
    - `invalid_workflow`: not an API-format graph at all (a UI-format save file, a `/prompt`
      body, or a node that isn't an object).
    - `workflow_too_large`: past **2,000 nodes**. A 10,000-node graph wedged ComfyUI's worker
      past what an interrupt could stop.
    - `missing_node_type`: a class this instance doesn't have, with near names. `/prompt`
      reports this without saying which node.
    - `prompt_no_outputs`: nothing in the graph is an output node.
    - `bad_linked_input`, `linked_node_missing` and `linked_output_missing`: a link that isn't
      `["<node id>", <output index>]`, or points at a node or output the graph doesn't have.
      ComfyUI raises an exception on these instead of a clean error.
  - **Partner-API nodes**, which `workflow_run` refuses (see below).
  - **A warning, `not_connected_to_output`**, for a node no output depends on, because ComfyUI
    won't run it. It doesn't stop a run.

  Each problem names the `node_id`, `class_type` and `input`. Like ComfyUI, links are checked
  only on nodes an output depends on. One `/object_info` read (1.8 MB at v0.37.0) is shared for
  10 seconds, and an upload drops it, so the check is never older than that.

  It doesn't apply ComfyUI's node replacements (`/node_replacements`, which `/prompt` applies to
  a class that's no longer installed). An old class name is therefore `missing_node_type`: use
  the class that replaced it.

  The V3 dynamic-input naming (`images.image0` for an Autogrow, `resize_type.width` for a
  DynamicCombo's chosen option) lives in `workflow.py`, and `node_describe` renders it with the
  same helpers. Read-only.
- **`workflow_run`** runs `workflow_validate`'s check first, and refuses an invalid graph with
  those errors (`workflow_invalid`). It refuses any graph with a **partner-API node**
  (`partner_api_nodes_refused`, naming the nodes; see below). Otherwise it submits the graph
  to `/prompt`, where ComfyUI checks input types and values, and returns `job_id` and
  `prompt_id` at once. The relay chooses the ID, and on ComfyUI v0.37.0 they're the same. An
  older ComfyUI that mints its own `prompt_id` answers with a different one, and the `job_id`
  then finds the run only while this relay holds it.

  When ComfyUI refuses the graph, `workflow_run` fails at once with `workflow_rejected`, and
  nothing is queued. Its `job_id` only repeats the rejection: `job_status` reports it `failed`,
  with `comfyui_state` `rejected`. The
  error carries ComfyUI's own error and its per-node errors, also flattened into the same shape
  as `workflow_validate`'s problems (`type`, `node_id`, `class_type`, `input`, `details`,
  `expected`, `got`). So a MASK wired into SaveImage's IMAGE input comes back as
  `return_type_mismatch` on that node's `images`, in ComfyUI's words.

  ComfyUI accepts a graph when any output passes its checks, and drops the outputs that fail.
  The dropped ones come back as warnings.

  Follow the job with `job_status`. Its `progress` says where ComfyUI has the prompt:
  `comfyui_state` is `submitting`, `queued` (with `queue_position`, where 0 is next), `running`
  or `finished`, or `rejected` for a run ComfyUI refused. The run polls `GET /api/jobs/<id>` twice a second, which is about 150 bytes
  while the prompt waits or runs. Only `queue_position` needs `/queue`, which carries every
  queued graph: one read is shared by all runs for 2 seconds, and only while a run is queued.
  A ComfyUI without the jobs API is followed through `/queue` and `/history/<id>` instead. The
  executing node isn't reported, since that needs ComfyUI's websocket.

  A finished job's `result` lists the saved files. A failure is a structured `error`:
  - `workflow_execution_failed`: the node id and type, the exception type and message, and
    the last traceback lines;
  - `workflow_interrupted`: something other than this job stopped it;
  - `workflow_vanished`: ComfyUI lost it (another client dequeued it, or ComfyUI restarted).

  If ComfyUI stops answering, a run waits up to 60 seconds for it to come back. What the graph
  does is up to its nodes: this server reaches only ComfyUI, but a custom node installed there
  may write anywhere ComfyUI can, or reach the network.
- **`workflow_outputs`** lists a finished run's files: node, `kind` (images, gifs, audio,
  ...), filename, subfolder, `type` (output or temp), MIME type, and size from a `HEAD /view`
  for the first 32 files. It also lists non-file outputs such as text. Failed and cancelled
  runs are listed too, since they may have saved something. **It streams nothing unless
  asked.** `fetch=<filename>` returns that one file inline, up to **5,000,000 bytes**, and
  sizes only that file: an image as MCP image content the model can see, audio as audio
  content, anything else as an embedded resource. A larger file is refused
  (`output_too_large`) with its `/view` path, which a person or tool with direct access to
  ComfyUI can use. After a restart it finds the run on ComfyUI by its ID
  (`source: "comfyui"`). Read-only.
- **`workflow_upload_input`** puts a file into ComfyUI's input directory through
  `POST /upload/image` (`type=input`) and returns the name ComfyUI stored it under, to put in
  LoadImage's `image` input.
  - The file arrives base64-encoded, at most **10 MiB** decoded. A `data:` URL is fine, and so
    are line breaks and other whitespace (MIME-style wrapped base64).
  - With the `run` profile enabled, the HTTP transport accepts a request body of up to 10 MiB's
    base64 plus 1 MiB. The SDK's default is 4 MiB, which refused a 3 MiB file before the tool
    ran. So an upload a little over the cap gets `upload_too_large`; only one over about
    10.75 MiB meets the transport's bare 413. Without `run` the SDK's 4 MiB default stands. The
    token is checked before any body is read.
  - Uploads decode and send one at a time. **Memory:** see *Memory* below.
  - The name is sanitised: directories are dropped, anything outside `A-Z a-z 0-9 . _ ( ) + -`
    and space becomes `_`, and leading dots go. A name with nothing left is refused.
  - It never overwrites: a different file under a taken name is stored as `name (1).ext`
    (`renamed: true`), and the same bytes again reuse the file that's there. It writes nowhere
    else. There's no mask variant: `/upload/mask` edits the alpha of an image that's already
    there.

**Memory.** A `run`-profile sidecar idles at about 90 MB RSS, and one maximum-size upload
peaks at about 150 MB. Most of what a large upload costs is its request body, which the
transport reads and parses before the tool runs, however the tool queues the uploads
themselves. So the server admits at most `COMFYUI_MCP_MAX_LARGE_REQUESTS` (default 2)
`POST` requests over 1 MiB at once, in front of the transport and behind the token; one more waits up
to 5 seconds, then gets a retryable `503`.

The SDK also keeps each MCP session's last request, body included, until that session sends
its next message or has been idle for 30 minutes (its session timeout). So each client that
has just uploaded a large file holds about 25 MB more, and the cap can't bound that. Six
maximum-size uploads at once, from six sessions, peaked at about 300 MB with the cap and about
350 MB without it; the same six one after another peaked at about 290 MB, and six through one
session at about 170 MB (measured at v0.37.0, image built from 5.0.0's tree). **256 MiB** fits
the default cap with up to three clients that upload large files. Allow about 25 MB per
client beyond that, and more if you raise the cap.

**Annotations.** `workflow_validate` and `workflow_outputs` are read-only. `workflow_run` isn't
read-only, since it queues work and ComfyUI writes new output files. It isn't destructive
either: it replaces or deletes nothing, and SaveImage numbers its files rather than
overwriting them. It isn't idempotent, since every call is a new run. `workflow_upload_input`
isn't read-only, since it adds a file to the input directory, and isn't destructive, since it
never overwrites. It is idempotent, because the same bytes under the same name are stored
once. All four are closed-world as far as this server goes: they reach only `COMFYUI_URL`.

**Partner-API nodes** call paid external services with the user's Comfy.org credentials, and
v1 never runs them (#103). `workflow.partner_signals` decides, from `/object_info`, and the
refusal names each node and its signals:
- `api_node`: the class's `api_node` is truthy. ComfyUI sets it from `API_NODE`, and
  `--disable-api-nodes` and the editor's badge use the same flag. At v0.37.0, 271 of 959
  classes have it.
- `comfy_org_credentials`: a hidden input of type `AUTH_TOKEN_COMFY_ORG` or `API_KEY_COMFY_ORG`,
  which is how such a node is handed the credentials that pay. This adds three classes that
  aren't flagged: `ByteDanceCreateImageAsset`, `ByteDanceCreateVideoAsset` and
  `Krea2StyleReferenceNode`.
- `comfy_api_nodes`: the class comes from ComfyUI's own partner-API package
  (`python_module` starts with `comfy_api_nodes.`).

Template runnability and node search use the same function. **The backstop:** at v0.37.0 a
partner-API node gets the user's Comfy.org credentials only from `/prompt`'s `extra_data`
(`execution.py`: `extra_data.get("auth_token_comfy_org")`), and this server never sends
`extra_data`. Its `/prompt` body is exactly `{prompt, prompt_id}`, and a test holds it to that.
So even a partner node that escaped detection would run without the credentials that pay. A
custom node that spends money by some other route shows no signal and can't be detected.

**Cancelling.** `job_cancel` on a run stops its prompt with ComfyUI's atomic cancel,
`POST /api/jobs/<id>/cancel`. Under ComfyUI's queue lock, that dequeues the prompt if it's
waiting and interrupts it only if it's the prompt running. It never sends `/interrupt`, which
at v0.37.0 checks the running prompt outside the lock, and without a prompt id stops whatever
is running. The stop then checks `GET /api/jobs/<id>` until the prompt is no longer pending or
in progress. It sends the cancel again at each check, because ComfyUI clears its interrupt
flag as a prompt starts executing, so an interrupt that lands at that moment is lost. A
timeout or a reset connection is retried the same way. Only a non-retryable answer, or the
deadline, ends the stop early. The whole unwind takes at most 2.5 seconds, inside the producer
contract's 3, and each call has a 1-second timeout. ComfyUI's own terminal status decides what
happened: `cancelled` means the stop worked, and `completed` or `failed` means the prompt got
to the end first.

`job_status` and `job_cancel` report the outcome in `progress.stop`:
- `confirmed`: ComfyUI shows it cancelled, either dequeued before it ran or interrupted.
- `already_finished`: it had finished before the cancel took effect, so the cancel changed
  nothing. The job then ends as the prompt did: `succeeded` with its `result`, or `failed` with
  ComfyUI's error. `progress.comfyui_state` is `finished`, and `workflow_outputs` lists what it
  saved. Keeping the result is deliberate. The work was done and its files exist, so dropping
  them would report a cancel that didn't happen. If ComfyUI only says so after the stop's
  budget has run out, the job has already ended `cancelled`. `progress.stop` still becomes
  `already_finished`, and `workflow_outputs` lists the files.
- `unconfirmed`: it couldn't be checked in time, and `stop_detail` says why. The stop carries
  on in the background for up to 30 seconds, re-sending the cancel while ComfyUI still has the
  prompt. Once ComfyUI says how the prompt ended, `stop` changes to match and `stop_detail` goes.
- `not_stopped`: it's running, and this ComfyUI has no atomic cancel. The prompt is left to
  finish rather than risk interrupting someone else's.
- `not_needed`: ComfyUI refused the submission, so nothing was queued.
- `left_running`: see below.

A cancel that arrives while the submission is still in flight doesn't abandon it. ComfyUI
goes on queueing a prompt whose client hung up, so the stop waits for ComfyUI's answer and then
cancels by id. If there's no answer within the budget, it cancels by the prompt id it chose,
records `unconfirmed`, and cancels again once ComfyUI answers. A second `job_cancel`, or a
shutdown, while a cancel is unwinding doesn't interrupt that unwind.

**A stopping relay leaves its runs running** (owner decision on #145). A shutdown cancels
every job with the reason `shutdown`, and a workflow run then ends at once with `progress.stop`
set to `left_running`: the prompt carries on in ComfyUI, and a restarted relay re-attaches to
it.

**Re-attaching after a restart** (#146). ComfyUI is the source of truth for a run, and
re-attaching is read-only. A run's `job_id` is the `prompt_id` the relay chose when it
submitted it, so when `job_status` or `workflow_outputs` get an ID this server doesn't hold (it
restarted, or dropped the finished job), the run is looked up on ComfyUI. Nothing about it is
kept in the relay.
- **Where the prompt is** comes from `GET /api/jobs/<id>`. A prompt that is `pending` or
  `in_progress` is `running`, as a held run is, with `progress.comfyui_state` of `queued` (and
  its `queue_position`) or `running`.
- **How a finished one ended** comes from its `/history/<id>` entry, through the same mapping a
  held run's result goes through. So a re-attached run reports exactly what the relay that held
  it would have: `succeeded` with its files, or `failed` with the same structured error
  (`workflow_execution_failed` naming the node, or `workflow_interrupted`). `/api/jobs`'s own
  outputs aren't used, because ComfyUI normalises them (a 3D file name becomes a file, `None`
  entries are dropped), and they would differ from `workflow_outputs`.
- The view says `source: "comfyui"`. `created_at`, `started_at` and `finished_at` are ComfyUI's
  times. `summary` is generic, because the graph isn't read back.
- `job_status` with `timeout_seconds` polls ComfyUI twice a second, and rides out ComfyUI not
  answering for up to 60 seconds, as a held run does. Concurrent waits on one ID aren't
  shared: each poll is about 150 bytes, and each wait ends within 300 seconds.
- Only a canonical UUID (lowercase, hyphenated) can be a run's ID. Any other ID this server
  doesn't hold is `unknown_job` at once, and never reaches ComfyUI.

Limits, all ComfyUI's:
- A prompt cancelled before it ran leaves no record, so it's `unknown_job`, like any ID
  ComfyUI doesn't know. So is every prompt after ComfyUI itself restarts, since it keeps its
  history in memory.
- ComfyUI doesn't record who interrupted a run. A re-attached run that was interrupted is
  `failed` with `workflow_interrupted`, whose message says something else stopped it, even if
  the relay cancelled it before restarting.

**Cancelling is refused** for any job this server doesn't hold (`job_not_held`), and nothing
is sent to ComfyUI. After a restart the relay can't tell its own prompts from other clients',
and cancelling by ID alone would let an agent stop someone else's work. **A person can cancel
an orphaned run from ComfyUI's queue panel.**

**Privacy.** `job_status` and `workflow_outputs` read any prompt on the ComfyUI by its ID,
including another client's: its status, its error, and its output files. That's by design and
bounded. The ID has to be known already: prompt IDs are random UUIDs (the relay's own, and the
ones ComfyUI mints for other clients), so they can't be guessed, and no relay tool lists
ComfyUI's queue or history. The relay is token-gated with one principal (see *Job access is
per token*), so this adds no reader who couldn't already follow the relay's own runs. What
comes back is mapped: the graph and its `extra_data` aren't returned. A deployment that must
keep other clients' runs from the relay's agents entirely should give the relay its own
ComfyUI.

## UI-to-API conversion

The `mcp-convert` image (#167; `comfyrelay/convert.py`). ComfyUI has no conversion route, so the
relay drives a headless Chromium against the frontend `COMFYUI_URL` serves: it loads the UI
graph with `app.loadGraphData` and returns `app.graphToPrompt()`'s output, through JSON as the
editor's Export (API) writes it. The conversion is the editor's own, so it follows that
frontend version's rules, bugs included. There is no fallback converter.

- **`template_get`** takes `format: "api"`.
- **`workflow_validate`** and **`workflow_run`** take a UI-format graph (a top-level `nodes`
  list and `links`) and convert it first; the result says `converted_from_ui`.
  `workflow_validate` returns the API graph it checked in `workflow`, unless it is over 80,000
  characters as JSON (`workflow_omitted` says so). `workflow_run` refuses a UI graph with a
  partner-API node before converting it, from the graph's own node types, inside subgraphs
  too, so such a graph gets `partner_api_nodes_refused`, never a conversion error. An
  API-format graph is never converted.
- **When it can't convert**, the call fails with `conversion_unavailable` (conversion is off,
  this image has no browser, the browser didn't start, the frontend didn't load, the tab or the
  browser went away mid-conversion, or every tab stayed busy for 60 seconds; retryable but for
  the first two) or `conversion_failed` (the frontend threw, or didn't answer within 30 seconds),
  each with the reason. `template_get`'s error carries the UI graph in
  `workflow` when it fits 80,000 characters, and `workflow_omitted` otherwise.
- **`server_info.capabilities.conversion`** reports `state`: `off` (with why: no browser in
  this image, or `COMFYUI_MCP_CONVERT` isn't `1`), `unavailable` (a `COMFYUI_URL` it won't lock
  to, below), `ready` (the browser starts on the first conversion), `running`, `backing_off`
  (with `retry_in_seconds`) or `stopped`, plus `pages`, `conversions` and, once a tab has
  loaded it, `frontend_version`.

**The lockdown** keeps the browser off the network entirely: the relay fetches what the frontend
may read and hands it over. It is tested against a real Chromium (`tests/test_relay_convert_live.py`),
with the ComfyUI it converts against replaced by a stand-in that forwards plain `GET`s to a real
ComfyUI and records every request it receives. A page script tries every way out: writes to
ComfyUI, a `GET` off the allowlist, another origin, websockets from the page and from a worker, a
worker's and a nested worker's fetch, a `SharedWorker` (also one taken from a fresh `about:blank` or
`srcdoc` iframe), speculation-rules prefetch and prerender, a beacon, an iframe, a popup, a
preconnect, WebRTC and WebTransport. In a plain browser each gets out (the negative control; all
but the preconnect, which the headless shell doesn't make even unblocked). In a converter tab none
does, and every request the stand-in received from it was an allowlisted `GET` the relay sent.

1. **Requests.** A route on each tab takes every request it sees. A `GET` to the `COMFYUI_URL`
   origin for a path on the allowlist below is fetched by the relay itself, and the page gets
   ComfyUI's answer; everything else is aborted. The path is checked relative to `COMFYUI_URL`'s,
   percent-decoded once and twice (some ComfyUI routes, `/api/userdata`'s among them, decode a
   second time): a `%25` anywhere refuses it, and so does a `.` or `..` segment or a backslash after
   either decode. The relay's fetch (`httpx2`) is a `GET` of a URL it rebuilds from `COMFYUI_URL`
   and the checked path, with a few request headers such as `Accept` and `Comfy-User`, no body, a
   cookie jar that keeps nothing, and no redirect followed. It streams the answer and gives up on
   one over 32 MiB (the page gets an abort); at most 6 run at once, and only one of those may hold
   more than 4 MiB. A 32 MiB answer is copied a few times on its way to the page (about 150 MB at
   once); the live test holds the relay process's growth under 300 MB while it is sent 600 MB of
   large answers and 24 smaller ones at once. A ranged request
   (a video preview's, `Range: bytes=0-`) is passed on with its range cut to 4 MiB, so an input
   video of any size is read in pieces of at most 4 MiB, as far as the preview asks for. One refused
   request is answered rather than aborted: a `POST` of the frontend's own settings
   (`/api/settings`, `/api/settings/<id>`), which it makes as it starts (`Comfy.InstalledVersion`,
   on a ComfyUI no browser has opened) and without which it stops loading. It gets an empty `200`
   from the relay and is never sent. Every page websocket is closed before it connects.
2. **Page APIs.** An init script, run before any page script in every frame, `about:blank` and
   `srcdoc` iframes included, removes `SharedWorker`, `RTCPeerConnection`, `RTCDataChannel` and
   `WebTransport`, and makes `navigator.sendBeacon` refuse. Dedicated workers stay, because the
   frontend starts two from `blob:` URLs as it loads.
3. **The network.** Chromium itself reaches nothing, ComfyUI included: every connection goes to a
   proxy whose name never resolves, and its resolver answers `NOTFOUND` for every name. So what
   the route doesn't see goes nowhere: a worker's websocket, a speculation-rules prefetch or
   prerender (both measured reaching ComfyUI when its origin went direct), a preconnect, a DNS
   prefetch. WebRTC may not use UDP outside a proxy, and QUIC is off.

The allowlist, measured over every template ComfyUI v0.38.0 serves (frontend 1.53.6):

| Kind | Paths |
|---|---|
| Exact | `/`, `/user.css`, `/materialdesignicons.min.css`, `/internal/folder_paths`, and `/api/` + `object_info`, `settings`, `system_stats`, `users`, `userdata`, `i18n`, `extensions`, `features`, `experiment/models`, `global_subgraphs`, `jobs`, `view` |
| Under | `/assets/`, `/fonts/`, `/api/global_subgraphs/`, `/api/userdata/`, `/extensions/` (custom-node JavaScript; none on a bare ComfyUI) |

Each of those routes only reads. The frontend asks for one more ComfyUI path, refused on purpose: on
a ComfyUI no browser has opened, its first-run template browser reads `/api/workflow_templates`, and
would then load every template's thumbnail, about 250 MB a tab, for nothing a conversion needs.

`/api/view` (a loader's input file, for its preview) has to stay: once a video's preview has loaded,
`LoadVideo` exports a `video-preview` input it lacks otherwise (62 templates differ without it, with
their input files present). That makes the editor's own export depend on how fast the preview loads,
so after loading a graph the relay waits until the tab's fetches have been quiet for 0.3 s, counted
from when the wait began or the last fetch, whichever is later, and at most 10 s (the frontend gives
a preview 8.2 s), before it exports. When the 10 s run out with fetches still in flight, it exports
anyway and logs a warning naming them. On a host starved of CPU, a preview can take longer than that:
the export then lacks a UI-only input such as `video-preview` (a review at 0.25 CPU lost 3 or 4 of
20). ComfyUI ignores that input, so the run is the same. With a real file for each of the 546 inputs the templates name,
every template converts the same as the frontend's own export made after waiting for each
`LoadVideo`'s preview widget itself, not for the network (573 of 573; 62 carry `video-preview`).

What the frontend asks for that is refused, and it converts without: `api.comfy.org`
(release notes), `huggingface.co` (it checks the template's model links with `HEAD`), ComfyUI's
`/ws`, and `POST /api/upload/image` from Load3D, which makes those graphs fail with
`conversion_failed`.

**What stays reachable** is the allowlist, as ComfyUI implements it: every route on it only
reads on a bare ComfyUI v0.38.0, checked in its handlers. Query strings aren't checked, so a
parameter such as `/api/userdata`'s `dir` is left to ComfyUI's own path checks. Under
`/extensions/`, any `GET` route a custom node registers there is reachable, and custom-node
JavaScript loads and runs in the page, because a custom node's widgets can change what the
export writes; it runs under the same lockdown, and a custom node whose graphs need its own `GET`
routes elsewhere won't convert. **The browser runs without its sandbox** (`--no-sandbox`):
Docker's default seccomp profile with `no-new-privileges` leaves it none it can use. A
compromised renderer would run as the relay's UID, in the container that holds
`COMFYUI_MCP_HTTP_TOKEN`. The browser and the Playwright driver don't inherit the token: the server
removes it from its own environment once read, and the browser is launched with only `PATH`, `HOME`,
`TMPDIR`, the locale and the time zone. But it is still readable by any process with the relay's UID,
a compromised renderer included: in the server's own `/proc/<pid>/environ`, which keeps the
environment the process started with, and in PID 1's. A
`COMFYUI_URL` with credentials in it is refused for conversion (`unavailable`), so they never
reach the browser; the server still uses them. The page never queues a prompt, so no
`extra_data` reaches ComfyUI from it.

**Lifecycle.** One browser per relay, started on the first conversion and reused. Each tab is
a browser context of its own, with storage of its own: the frontend saves the open workflow to
storage, and a tab that shared it restored the previous tab's workflow over the one it was
asked to convert. The frontend keeps every graph it loads (about 5 MB each), so a tab is
replaced after 25 conversions, the first ones staggered so the tabs don't reload together, and
after any failure. The Playwright driver grows too, so after 500 conversions the browser and
driver are retired once their conversions finish, and started again. A browser that fails to
launch backs off (5 seconds, doubling to 5 minutes) instead of every call retrying it, and
one that went away is started again. A tab or browser that goes away under a conversion
(a crashed renderer, a killed browser) is `conversion_unavailable`, retryable, not the graph's
failure. On `SIGTERM` the server closes it.

**What it is tested against.** The frontend `COMFYUI_URL` serves does the conversion, so its
version decides the result, and the allowlist was derived on one: frontend 1.53.6, which ComfyUI
v0.38.0, this image's pin, serves. `capabilities.conversion.frontend_version` reports the one in
use. Against `core:nightly`, or a ComfyUI started with another `--front-end-version`, it is
untested; a frontend that needs a path the allowlist lacks fails to load, as
`conversion_unavailable`. A ComfyUI started with `--multi-user` isn't supported: the frontend waits
for someone to choose a user, so every conversion is `conversion_unavailable` after about 30
seconds. CI's `relay-convert` job runs the image's probe and these live tests, apart from the
`relay` job, so a failure here never holds back the `mcp` image.

**Updates.** The Chromium build is pinned by the Playwright version, and checked by a hash over
its files, which pins integrity, not freshness: Chromium's security fixes reach the image when
Playwright moves, which is meant to follow each Playwright release, about monthly
(`dockerfile.comfy.relay`).

**Sizing**, measured with the image as UID 54321 on a read-only root with a tmpfs on `/tmp` and
`--memory 3g`, against a booted core-cpu whose input directory holds a real file for every input
the templates name (546 of them), on 8 CPUs of a Ryzen 7 5825U:

| With 2 tabs | Memory (PSS, every process) | Time |
|---|---|---|
| Before the first conversion | 99 MB | |
| The first conversion, which starts the browser | 1.13 GB | 5.3 s |
| Idle once warm | 1.12 GB | |
| 40 conversions in a row (`workflow_validate`) | 1.50 GB peak | median 0.56 s, p95 0.89 s (previews settle); the same call on the API graph takes 0.004 s |
| 6 at once | 1.55 GB peak | 2.9 s for all six (0.53 to 2.87 s each) |
| 200 more in a row | 2.39 GB peak (the cgroup's own peak, over the whole run: 2.32 GB) | median 0.55 s, p95 1.05 s |
| Idle after those | 1.41 GB (the driver has grown to 330 MB) | |

Large inputs don't change that: `LoadVideo` graphs whose input is a 410 MB video, one at a time and
six at once, peaked the cgroup at 1.97 GB, every one exporting its `video-preview` as the editor
does. Before the fetch was bounded, a 300 MB input video ran a 3 GiB container out of memory. A graph
with nothing to preview converts faster, but every conversion waits at least 0.3 s for the tab's
network to go quiet (the review after the settle wait measured a median of about 0.37 s for a
template with no loaders).

Give it a memory limit of at least 3 GiB with 2 tabs, and about 265 MB more for each extra tab.
The image is 304 MB to pull and 1.18 GB on disk, against 63 MB and 280 MB for `mcp`: the compressed layers
in the registry manifest, and `docker image ls` DISK USAGE on Docker 29's containerd image store, which
keeps the compressed layers beside the unpacked ones (measured on main's `mcp-convert:ad8420ac`).

## Docs tools

The `read` profile's `docs_search` and `docs_guide` (#134), in `comfyrelay/tools_docs.py`, read
a docs index built into the image. They reach nothing at runtime, not even ComfyUI, and they don't
merge results with the live node and template tools.

- **`docs_search`** searches two sources section by section (SQLite FTS5, stemmed), best first:
  - **docs.comfy.org**: every English page that the `navigation` in Comfy-Org/docs'
    `docs.json` lists, at the `COMFY_DOCS_SHA` bake pin. That's the workflow JSON spec, the
    server's routes and websocket messages, custom node development, tutorials, the
    interface, troubleshooting and the built-in node pages. The site describes the latest
    ComfyUI, not the pinned one, so a response with any result from it carries a `note`
    saying so.
  - **guides**: this project's own, the published skill
    [`skills/comfyui-workflows/`](../../skills/comfyui-workflows/SKILL.md).

  Every result gives its `source`, `version`, `path`, `license` and upstream `url`, the page
  `title`, the `section` (its heading trail) and the section's text. A section longer than
  1,500 characters is cut to the stretch that holds the most query words, stems included,
  with some text before the first of them. A guide's result also names its `docs_guide`
  `topic`. A query longer than 500 characters is refused. Common question words are dropped
  from it, each word counts once, and only the first 16 distinct words left are searched;
  the response's `searched` lists them. Every one of them must match; when no
  section has them all, sections with any of them are returned, `match` says `any`, and a
  `hint` suggests narrowing the query. The search runs in a worker thread, so a slow one
  doesn't hold up the other tools.
- **`docs_guide`** lists the guide topics with a summary each, or returns one topic's markdown.
  The topics are the files the skill's `SKILL.md` links to, including the separate
  `comfy-manifest` skill. An unknown topic fails with `unknown_topic` and the list.

**The docs index** is built by `comfyctl relay docs build` in the image's `docs` stage
(`comfyrelay/docs_index.py`). It fetches Comfy-Org/docs with a shallow, sparse `git` fetch: only
`docs.json`, the snippets and the pages it lists, with no history and no media. It converts
each page from MDX to markdown: front matter goes (the title and description are kept),
along with `import` lines, JSX and HTML tags, images and videos, and fenced code stays. A
component imported from `/snippets/` is replaced by that snippet's text. The navigation's
OpenAPI operation entries (`GET /nodes`, generated from a spec) aren't files, so they're
skipped and counted. The guides come into the build as the `skills` named context.

At the pin that is 1,644 pages in 8,407 sections, plus 5 guides: a 16 MB index. The build
step, fetch included, took about 6 seconds here. The image grows by about 31 MB: the index,
and 14 MB of markdown shipped beside it.

**Licensing.** Comfy-Org/docs is GPL-3.0, so the index is a GPL-3.0 work, and the image
ships what that needs: the English markdown it indexed, the snippets it used and the
`docs.json` that chose the pages (`/opt/docs/source/`), the GPL-3.0 text (`/licenses/GPL-3.0.txt`), and `/licenses/NOTICE`.
The NOTICE names the docs repo and commit and the license, dates the modification, gives the
build script's path at the commit the image was built from (the `GIT_SHA` build arg, which CI
passes; a build without it names the release tag of its version), and says "© Comfy Org. Not
affiliated with or endorsed by Comfy Org." Each guide's `url` names the same commit. The relay's code stays MIT: it reads the docs index as a data file, an
aggregate. The image is labelled `org.opencontainers.image.licenses="MIT AND GPL-3.0"`. The
guides are our own words under MIT; they link to docs.comfy.org and copy none of it.

**Bumping the docs** is a PR that changes `COMFY_DOCS_SHA` (a supply-chain pin) to a commit
on Comfy-Org/docs `main`. GitHub serves any commit in the repository's fork network by its
SHA, so check the new one: `gh api repos/Comfy-Org/docs/compare/<sha>...main` must say
`ahead` or `identical`. CI's `docs-pin` job runs that check on every PR that changes
`docker-bake.hcl`. The build
probe fails the image if the docs index is missing or `docs_search` finds nothing.

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
