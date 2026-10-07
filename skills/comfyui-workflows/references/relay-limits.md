# comfyrelay: what the sidecar will and won't do

*Needs the comfyrelay sidecar.* This whole topic is about the MCP server this repository
ships beside a ComfyUI instance. Skip it if you reach ComfyUI some other way.

comfyrelay is one MCP server per ComfyUI instance, reached over HTTP with a
bearer token. It talks to its own ComfyUI and nothing else. Call `server_info`
first: it names the instance, its active profiles and tools, and the ComfyUI
version it was built for next to the one that's running.

## Profiles decide which tools exist

The operator picks capability profiles with `COMFYUI_MCP_PROFILES` (default
`read,run`). A tool outside the active profiles isn't listed, and calling it
fails as an unknown tool, so check `server_info` rather than assuming.

| Profile | Tools |
|---|---|
| `read` | `node_search`, `node_describe`, `model_list`, `template_search`, `template_get`, `docs_search`, `docs_guide` |
| `run` | `workflow_validate`, `workflow_run`, `workflow_outputs`, `workflow_upload_input`, `job_status`, `job_cancel` |
| `manage` | nothing yet |

`server_info` is in every profile.

## What it refuses

- **Installing anything.** No node packs, models, packages or updates, and no
  restarting ComfyUI. Propose a manifest change instead (the
  `models-and-nodes` topic).
- **Partner-API nodes.** A graph with a node that calls a paid external service
  is refused by `workflow_run` with `partner_api_nodes_refused`, naming each
  node, and nothing is submitted. `workflow_validate` and the template tools
  flag those nodes in advance. The relay decides from `/object_info`: the
  node's `api_node` flag, Comfy.org credential inputs, or a class from ComfyUI's
  partner-API package.
- **The UI format, unless it converts.** The `mcp` image's `workflow_run` takes
  API-format graphs only. The `mcp-convert` image converts a UI-format graph
  first, through the instance's own editor; `server_info.capabilities.conversion`
  says which you have (the `workflow-formats` topic).
- **Anything but its own ComfyUI.** It makes no other outbound connection, so
  docs answers come from the docs index built into its image, not the web.

## Jobs

`workflow_run` returns a `job_id` at once, and the run continues in ComfyUI.

- **Follow it** with `job_status`. Pass `timeout_seconds` to wait up to that
  long for the end (at most 300), and keep each wait under your client's own
  tool-call timeout, which is often about 60 seconds. A wait that times out
  leaves the job running; call again.
- **Collect files** with `workflow_outputs`. It lists them and returns one
  inline when you name it in `fetch`, up to 5,000,000 bytes.
- **Stop it** with `job_cancel`, which uses ComfyUI's per-prompt cancel and
  never interrupts someone else's run.
- A run's `job_id` is its ComfyUI `prompt_id`.
- At most `COMFYUI_MCP_MAX_JOBS` (default 16) jobs run at once. Past that a
  submission fails with `too_many_jobs`.

## After the relay restarts

Jobs live in the relay's memory, but ComfyUI keeps the runs. Because a run's
`job_id` is its `prompt_id`, a restarted relay can still find it:

- `job_status` and `workflow_outputs` look an unknown id up on ComfyUI and
  answer with `source: "comfyui"`. How it ended comes from ComfyUI's history,
  in the same shape a held job reports.
- `job_cancel` refuses a run the relay doesn't hold, with `job_not_held`, and
  sends nothing to ComfyUI. After a restart the relay can't tell its own runs
  from other clients', so a person cancels such a run from ComfyUI's queue.
- If ComfyUI itself restarted, its history is gone too, and the id is
  `unknown_job`.

## Errors

A failed call's text ends in JSON: `{"error": {"code", "message",
"retryable"}}`. Branch on `code`. `retryable: true` means the same call can
work later unchanged, for example while ComfyUI restarts.
