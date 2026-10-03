# MCP evaluation harness (Phase 1)

This harness scores three MCP servers on what an agent actually gets done against this repo's pinned `core-cpu` image. It is Phase 1 of #100, tracked in #102. Each task pairs a prompt with a check script, and every check verifies the outcome through ComfyUI's HTTP API or the filesystem. No check reads an agent transcript.

Each server runs in the best reasonable configuration, the owner's call on #102. What each one does as shipped is recorded under *Findings*.

| Server | How it runs here | Config |
|---|---|---|
| [Comfy-Org/comfy-mcp](https://github.com/Comfy-Org/comfy-mcp) | stdio, `uv run` with `comfy-mcp==0.10.0`, `comfy-cli==1.21.0` and `mcp==2.0.0`, so real errors come through (finding 2). `COMFY_LOCAL_URL` is `COMFY_URL`. | `servers/comfy-mcp.json` |
| [artokun/comfyui-mcp](https://github.com/artokun/comfyui-mcp) | streamable HTTP on `127.0.0.1:9100/mcp` (`ARTOKUN_PORT`), `npx comfyui-mcp@0.52.203`, full tool surface. The bearer token stays required, and auto-update and panel auto-install stay off. | `servers/artokun.json` and `artokun.sh` |
| [joenorton/comfyui-mcp-server](https://github.com/joenorton/comfyui-mcp-server) | streamable HTTP on `:9000/mcp`, from `ghcr.io/pixeloven/comfyui/mcp:2.4.1`, pinned by digest | `servers/joenorton.json` and `joenorton.sh` |
| comfyrelay, this repo's own ([#103](https://github.com/pixeloven/ComfyUI-Docker/issues/103)) | streamable HTTP on `127.0.0.1:9200/mcp` with a bearer token, from a local image (`COMFYRELAY_IMAGE`, default `ghcr.io/pixeloven/comfyui/mcp:local`, built from the checkout by `IMAGE_LABEL=local docker buildx bake mcp --load`), run read-only as UID 12345. Not in `run-all.sh`, which is the Phase 1 evaluation. | `servers/comfyrelay.json` and `comfyrelay.sh` |

Nothing is installed globally. uv, npm and comfy-cli keep their caches, `HOME` and config under the scratch directory.

## Running it

```sh
./up.sh                      # build the pinned core-cpu if needed (build.sh), start it, write results/instance.json
./groundtruth.sh             # results/object_info.json, plus the version and image digest beside it
./run.sh artokun probe       # start one server, send initialize + tools/list, stop. No agent.
./run.sh comfy-mcp T1        # dry run: reset T1, print the claude command, score, append a row
HARNESS_RUN=1 ./run-all.sh   # the real evaluation, 3 servers x 4 tasks. Needs the owner's approval.
./down.sh --purge            # stop everything and delete the scratch data
```

Subagents run the tasks against comfyrelay, artokun and comfy-mcp through `external.sh` instead; see *External-agent mode* and *Comparing servers* below.

- **Instance.** `up.sh` runs the image with `--network host`, Manager on, and every data volume under `$HARNESS_DATA` (default `/tmp/comfyui-harness`). It adds `CLI_ARGS=--listen 127.0.0.1`; see finding 5.
- **artokun restart.** `ARTOKUN_MANAGER_RESTART=1` lets artokun's `restart_comfyui` reboot ComfyUI through Manager's `POST /v2/manager/reboot`. It is set through `COMFYUI_RESTART_COMMAND`, as a `curl` to that endpoint, and gives artokun no Docker access. Off by default, so the scored baseline stays as shipped; see finding 7.
- **Other knobs.** `HARNESS_MODEL` (default `claude-opus-5-5`, pinned so every run is comparable), `HARNESS_TIMEOUT` (default 900 s) and `HARNESS_BUDGET_USD` (default 5 per run, a runaway guard only). `HARNESS_BARE=1` adds `--bare`, which also skips CLAUDE.md and user memory, but it needs `ANTHROPIC_API_KEY`.
- **The agent's sandbox.** The agent runs as `claude -p --restricted --tools Read,Write`, with only its server's tools allowed and `--permission-mode dontAsk`. It has no Bash, so it can't reach ComfyUI except through the MCP server. Its working directory is `$HARNESS_DATA/workspace`, which holds only the task's inputs, so it can't read `answers.json` or the ground-truth dump. Output is `stream-json`, so the transcript records every tool call.

### External-agent mode

`external.sh` runs a task with an agent the harness doesn't launch: a subagent of the lead session. Each step is its own command, so the lead can dispatch the subagent between them. `--server` picks comfyrelay (the default), artokun or comfy-mcp.

```sh
./external.sh up T5 [--server artokun]   # boot core-cpu if it isn't running (up.sh, then groundtruth.sh), reset the
                                         # task (its setup.sh), stop every other server, start this one, and print
                                         # the brief to give the agent
# the subagent does the task and writes its results file under the workspace
./external.sh check T5   # the task's check.sh; appends a scorecard row for the server `up` started; exit 0 on PASS
./external.sh down       # stop ComfyUI and every server; --purge also deletes what the harness created in $HARNESS_DATA
```

- **The brief** is what the lead hands the subagent, verbatim: a preamble, then the task's prompt. `up` prints it and writes it to `<workspace>/TASK.md`. The preamble says "the MCP server" and doesn't name it, though its tool names will. It gives the rules: use only that server, no direct ComfyUI calls, no docker and no network, read only the workspace (plus the token file, for an HTTP server), keep scratch files in the workspace and answers in its `results/`, and re-run a tool more narrowly rather than read a large result its own tooling saved elsewhere. Then it says how to reach the server:
  - **HTTP (comfyrelay, artokun).** The URL (`http://127.0.0.1:$COMFYRELAY_PORT/mcp` or `:$ARTOKUN_PORT/mcp`), the token file (`$HARNESS_DATA/.comfyrelay-token` or `.artokun-token`, mode 0600: outside the repo, `results/` and the workspace, so pointing the agent at it points it nowhere near the answers), and the MCP steps over plain HTTP (initialize, the `Mcp-Session-Id` and `MCP-Protocol-Version` headers, `notifications/initialized`, `tools/list`, `tools/call`, and `data:` lines when the answer is an event stream). The subagent speaks JSON-RPC with curl or a stdlib Python client, sending `-H "Authorization: Bearer $(cat <token file>)"`, so the token never lands in a config file or in the transcript.
  - **stdio (comfy-mcp).** The agent launches the server itself: the brief gives the exact command, its environment and its working directory (comfy-mcp's own `HOME` under `$HARNESS_DATA`), from `servers/comfy-mcp.json`, plus `UV_OFFLINE=1`, because `up` has already filled uv's cache with the probe. It launches it through `$HARNESS_DATA/bin/stdio_client.py`, a mode-0444 copy of `servers/stdio_client.py` outside the workspace and `tasks/`. `start` runs the server under a background broker that keeps that one process alive across calls, since comfy-mcp keeps state between them. `list`, `call <tool> '<json>'` (or `@file.json`) and `stop` each talk to it over a Unix socket in the workspace. The helper is stdlib only and contacts nothing but that process. It answers the server's own requests as a headless client would, so comfy-mcp's consent prompts (elicitation) get `cancel`, as they do under `claude -p`. `up` and `down` stop any broker an agent left running.

  The workspace is the agent's working directory, and the prompt's `results/...` paths are relative to it. The prompt is copied, so the agent is never pointed at `tasks/`, where the answers are.
- **Confinement is by instruction only.** The subagent has the lead session's tools, Bash included, and is *told* to use only its server and the workspace. Nothing stops it reading `tasks/`, calling ComfyUI directly, or reaching the network. So an `external` row says the server *can* do the task, not that a confined agent did. The confined, blind run is `claude -p` (below). `results/<task>.handoff.json` records the server, the brief, how to reach the server, the workspace and the server's tools, for the lead.
- **Tasks.** T1, T3, T4, T5 and T6 on every server. comfyrelay gets T2-refuse, because it must not install, and artokun and comfy-mcp get T2; `up` refuses the other pairing. T6's prompt names the relay's docs tools, so the other servers get `tasks/T6/prompt.neutral.md` ("from the documentation your MCP server can reach"). Its check is the same. `up` can be repeated for the next task on the same instance; each `up` restarts the server. `up` reuses a running core-cpu only when it runs the image `HARNESS_IMAGE` names now (compared by image ID, so a tag `build.sh` re-pointed doesn't match), on `HARNESS_DATA`, serving `COMFY_PORT`; it refuses otherwise. It runs `groundtruth.sh` whenever `HARNESS_RESULTS` has no dump yet, and T3's setup fails, rather than falling back to the committed answers, if there is still none.
- **T5's runnability oracle.** T5's check asks comfyrelay's `template_get` whether the chosen template is runnable, and whether one that needs a model isn't. So the oracle is the same whatever server the agent used. For comfyrelay, the check asks the relay `up` started, which must still be running. For artokun and comfy-mcp, `check T5` starts a relay for the check only, after the agent has finished, and removes it afterwards, so the agent never sees one.
- **Images.** `HARNESS_IMAGE` is the core-cpu to boot (default the local build from `build.sh`; `ghcr.io/pixeloven/comfyui/core:cpu-latest` works). T5's and T6's checks need `COMFYRELAY_IMAGE` whatever the server. `COMFYRELAY_IMAGE` is the relay under test (default `ghcr.io/pixeloven/comfyui/mcp:local`). Build it from the checkout with `IMAGE_LABEL=local docker buildx bake mcp --load`; on a host without a docker0 bridge, use `docker buildx build --network host` with the bake target's context, `skills` build context and args (`docker buildx bake mcp --print` lists them).
- **Isolation.** The containers run with `--network host`, and every server binds loopback. The relay refuses a port something already answers on. For several runs on one host, give each its own `HARNESS_CONTAINER` (the prefix of the container names), `COMFY_PORT`, `COMFYRELAY_PORT`, `ARTOKUN_PORT`, `HARNESS_DATA` and `HARNESS_RESULTS` (markers, derived answers, the scorecard; default `results/`; the agents' token files live in `HARNESS_DATA`). artokun's `HOME` and npm cache, and comfy-mcp's `HOME` and uv cache, are under `HARNESS_DATA` and persist from one task to the next. Nothing a run writes is tracked by git: the default `results/` is gitignored.

### Before each release

Before each release, the lead session runs T1–T6 against comfyrelay, built from the release commit, with one subagent per task, and posts the scores on the release PR (#135). The subagents are confined by instruction only (above), so the scores are labelled that way.

1. For each task: `./external.sh up <task>`, then dispatch a subagent with the printed brief verbatim and the workspace as its working directory, then `./external.sh check <task>`.
2. `./external.sh down --purge`, and post every `external (not sandboxed)` row the release run appended to `results/scorecard.csv`, retries included, on the release PR.
3. Look for `ANSWER DRIFT` in the T3 and T6 rows. It means a derived answer no longer matches the committed `answers.json`, because ComfyUI or the docs moved; the row says which answers and how to accept them, in a PR of their own.

### Comparing servers

The comparison scores comfyrelay against artokun and comfy-mcp: one subagent per server and task, through `external.sh`, not a billed `claude -p` (the owner, 2026-10-03). Every row is `external (not sandboxed)`, with the server in its own column. This is the local feature baseline. comfy-mcp runs on the host against the harness's ComfyUI and belongs only in this local comparison. It doesn't fit a cluster: per #102, many of its tools act on the local install that comfy-cli sees, not on a ComfyUI in a container. A cluster comparison will cover only the servers that deploy there.

From `tests/agent-tasks/`, with the relay image built (or `COMFYRELAY_IMAGE` set) and `ARTOKUN_MANAGER_RESTART=1` exported, so artokun can restart ComfyUI after its T2 install (finding 7). For each line, run `up`, dispatch a subagent with the printed brief verbatim and `$HARNESS_DATA/workspace` as its working directory, then run `check`:

```sh
export ARTOKUN_MANAGER_RESTART=1

# comfyrelay
./external.sh up T1;        ./external.sh check T1
./external.sh up T2-refuse; ./external.sh check T2-refuse
./external.sh up T3;        ./external.sh check T3
./external.sh up T4;        ./external.sh check T4
./external.sh up T5;        ./external.sh check T5
./external.sh up T6;        ./external.sh check T6

# artokun
./external.sh up T1 --server artokun; ./external.sh check T1
./external.sh up T2 --server artokun; ./external.sh check T2
./external.sh up T3 --server artokun; ./external.sh check T3
./external.sh up T4 --server artokun; ./external.sh check T4
./external.sh up T5 --server artokun; ./external.sh check T5
./external.sh up T6 --server artokun; ./external.sh check T6

# comfy-mcp (the agent starts and stops it through the helper the brief names)
./external.sh up T1 --server comfy-mcp; ./external.sh check T1
./external.sh up T2 --server comfy-mcp; ./external.sh check T2
./external.sh up T3 --server comfy-mcp; ./external.sh check T3
./external.sh up T4 --server comfy-mcp; ./external.sh check T4
./external.sh up T5 --server comfy-mcp; ./external.sh check T5
./external.sh up T6 --server comfy-mcp; ./external.sh check T6

./external.sh down --purge
```

`check` takes the server from the handoff that `up` wrote, so run each `check` before the next `up`. The brief is always `$HARNESS_DATA/workspace/TASK.md`, and the handoff is `results/<task>.handoff.json`.

The comparison isn't even in three ways, so read the rows with them in mind:

- **T5's prompt names comfyrelay's tools** (`template_search`, `template_get`, `workflow_run`), and asks for `runnable` as `template_get` reported it. An artokun or comfy-mcp agent has to map those to its own tools. comfy-mcp has close equivalents (`search_templates`, `get_template`'s `local_check`), and artokun has none that reads ComfyUI's template index.
- **T6 favours comfyrelay by construction.** The check accepts only a `path` that is a page in the relay image's own docs index, and q3 asks about comfyrelay itself. The neutral prompt changes only the wording.
- **T2 differs by design.** comfyrelay is scored on refusing the install (T2-refuse), and the others on doing it (T2). Per #102, comfy-mcp can't install into the container, and its consent prompt gets `cancel` from a headless client.

`claude -p` (`HARNESS_RUN=1 ./run.sh <server> <task>`) is the blind check: a fresh process with no lead session's context, given only its server's tools plus Read and Write in the workspace, and no Bash. Run it occasionally, for a comparison between servers; it needs the owner's approval.

## Tasks

| Task | The agent is asked to | `check.sh` passes when |
|---|---|---|
| T1 Workflow | Load `harness-input.png`, scale it to 256×256, invert it, and save it with prefix `t1_`. Built-in nodes only; no model needed. | A `/history` entry that's new since setup completed and has `ImageInvert`, and its `t1_*` PNG is 256×256 and bright on the left (the input is a black-to-white gradient). |
| T2 Node | Install ComfyUI-Custom-Scripts at commit `aac13aa7`, then evaluate `6 * 7` with `MathExpression\|pysssss`. | The class is in `/object_info`, the pack on the volume is the pinned commit (git `HEAD`, or registry version 1.2.5 when installed without `.git`), and a new `/history` entry used the class, completed and produced 42. `reset.sh` removes the pack and restarts ComfyUI. |
| T2-refuse Inverted T2 (#103) | The same request as T2, to a server that must not install (comfyrelay), plus writing what happened to `results/T2.json`: `installed`, `value` and `notes`. | Nothing was installed or restarted: the class isn't in `/object_info`, the `custom_nodes` volume matches what setup recorded, ComfyUI didn't restart (the container's `StartedAt` is unchanged and its log has no new `Starting server`, which also catches Manager's in-place reboot), and no new `/history` entry used the class. The report must be a JSON object with `installed: false` and a `value` key that is `null`; a claimed install or value fails. Setup runs T2's `reset.sh` first, so its own restart doesn't count. |
| T3 Introspection | Answer the 10 questions in `questions.json`, and write `results/T3.json`. | At least 9 of 10 match the answers `derive.sh` derives from this run's dump into `results/T3.answers.json` (the committed `answers.json` when there's no dump). The committed file is derived too, never written by hand; `derive.sh` reports where a new derivation differs from it, and never rewrites it. |
| T4 Failure | Submit `T4-workflow.json` unchanged, and report what happened in `results/T4.json`. | `succeeded` is `false`, `node_id` names the node ComfyUI rejected, and the report names the actual fault. ComfyUI's wording counts: its per-node error type or message, captured by setup from a real `/prompt` call. So does a client's own wording for the same fault: both types, MASK and IMAGE, plus "mismatch" or "expects". A success claim, or only the generic "Prompt outputs failed validation", fails. |
| T5 Template (#103) | A goal: a copy of an image at twice its width and height, from a workflow template. Choose one this instance can run with `template_search`, get it with `template_get`, run it unchanged with `workflow_run`, and write `results/T5.json`: `template`, `runnable` (as `template_get` said), `job_id` and `outputs`. Name only the files saved to `output/`, not temporary previews. Through `external.sh`, on every server; the prompt names comfyrelay's tools (see *Comparing servers*). | The template is one ComfyUI's `/templates/index.json` tags `Image Upscale`. Its job is a `/history` entry new since setup that completed, with the template's nodes and settings: the job runs each node class as many times as the template does (frontend-only nodes such as notes aside), and every value it sets on a node (every input that isn't a link; an empty dict or a null counts as unset, which is how a converter writes ImageCompare's display-only `compare_view`) is among the widget values of a template node of that class, so the input file, upscale method, factor and file prefix are the template's. Links aren't compared. Each output the index declares for it saved a file of that media type to `output/`, a PNG at twice the input's size, and the report lists exactly those files. Then the runnability check must match reality both ways, asked by the check itself: `template_get` says `runnable: true` for the template, and so does the report; and it says `runnable: false`, with missing models, for the first candidate whose template declares a model. |
| T6 Knowledge (#134) | Answer the 4 questions in `prompt.md` from the relay's built-in docs (`docs_search`, `docs_guide`), and write `results/T6.json`: each id maps to `{answer, path}`, the path being the search result or guide the answer came from. One question is from the workflow JSON spec, one from the server's routes, one only this project's guides answer, and one from a tutorial. It's run by a subagent, not a billed `claude -p` (owner, #134), through `external.sh`. artokun and comfy-mcp get `prompt.neutral.md`, which asks for the documentation their server can reach, with the same questions and check. | Every answer equals the one in `answers.json` as a whole, so a hedge such as "either X or Y" fails. Case counts where the question says so, and a route may drop its leading slash. Every cited path is a page in the image's own index where the question's pattern finds that same answer. `derive.sh` copies that index out of the relay image (`COMFYRELAY_IMAGE`, or its argument) to `results/T6-docs.sqlite` and derives `results/T6.answers.json` from it: each question names its page and a pattern, and the answer is what the pattern captures there. The committed `answers.json` is derived the same way, never written by hand, and `derive.sh` reports where a new derivation differs from it, so a docs bump that moves an answer shows up. |

**Why that node pack.** [ComfyUI-Custom-Scripts](https://github.com/pythongosssss/ComfyUI-Custom-Scripts) (pysssss) is MIT-licensed, has about 3.2k stars and is maintained. Its backend is pure Python with no `requirements.txt`, and its registry entry lists no dependencies. `MathExpression|pysssss` is an output node, so a one-node workflow runs it on CPU. The pin, `aac13aa7`, is the commit that registry version 1.2.5 was published from, so a git install and a Manager or registry install are the same code. The smaller alternative I checked, ComfyUI-Logic, is archived and has no license.

**Why these T3 questions.** They come in near-identical pairs that differ in exactly one value: `VAEDecodeTiled` vs `VAEEncodeTiled` `tile_size` step (32 vs 64), and `ImageScaleBy` vs `LatentUpscaleBy` `scale_by` (1.0 vs 1.5). Others have defaults a model tends to remember wrongly: `EmptyLatentImage` width is 1024 on v0.37.0, not 512. Scoring ignores the order of option lists but not output order, and accepts `"1.0"` for `1.0`.

**Why T5's goal and setup.** core-cpu has no models, and of the 564 templates ComfyUI v0.37.0 serves (`comfyui-workflow-templates` 0.11.66), 5 need none and use no partner-API node. Four of them load an example image that ComfyUI doesn't serve, and one of those upscales: `utility_interpolation_image_upscale` (LoadImage, ImageScaleBy by 2 with lanczos, SaveImage), so the goal is an upscale.
- **Setup** gives every template tagged `Image Upscale` (23 at 0.11.66) the input images its index entry names (`io.inputs`), as 512×384 stand-ins. That leaves models, nodes and partner APIs to decide which can run, which is what the relay's runnability check is for, without downloading a model.
- **What it tests.** A search for the goal returns model-based upscalers too (SeedVR2, Z-Image), so the agent has to choose by runnability rather than rank.
- **What's derived.** The candidates, their inputs and each one's output media type come from the live index. The template's node classes and widget values come from its own `/templates/<name>.json`, so a hand-built graph with another method or prefix fails. The runnability comes from the relay at check time, for the chosen template and for a candidate that declares a model. The outcome comes from `/history` and the output file on disk.
- **What's written by hand.** Only the goal: the `Image Upscale` tag, the factor 2 and the stand-in's size, in `harness.py`.
- **If templates change.** A template bump that adds a runnable upscaler is still a pass. One that removes it leaves no runnable answer, and T5 fails until its goal changes.

## Recording scores

`run.sh` and `external.sh check` append one row per run to `results/scorecard.csv`, with these columns: `timestamp, server, task, result, detail, seconds, mode, turns, cost_usd_notional`. `mode` is one of:

- `agent`: `claude -p`, sandboxed: only its server's tools, plus Read and Write in the workspace.
- `external (not sandboxed)`: a subagent through `external.sh`, told to use only its server and not stopped from doing otherwise. `seconds` runs from `up` to `check`, and there is no transcript, turns or cost.
- `dry-run`: no agent ran, and the row doesn't count.

`cost_usd_notional` is the figure `claude` reports; on a subscription the run uses plan quota, not money. The transcript goes to `results/runs/<server>-<task>.jsonl`, and whatever the agent wrote goes beside it.

The scorecard for #102 is built from those rows plus `results/instance.json`, which records the ComfyUI version and image digest. Everything under `results/` is gitignored. The committed ground-truth snapshot comes in Phase 4.

## Findings about the servers as shipped

These come from building the harness, before any agent ran. The evaluation results are on #102.

1. **comfy-mcp can drive the container for everything that goes through ComfyUI's HTTP API, but can't install nodes into it.** Our ComfyUI listens on `127.0.0.1:8188`, which is comfy-cli's default target, and `COMFY_LOCAL_URL` states it explicitly.
   - **Verified to reach the container:** `server_info`, `system_stats`, `nodes`, `validate_workflow` and `run_workflow`. Run through the tool, the T1 workflow passes `T1/check.sh`.
   - **Local-only tools can't:** `install_node`, `restart_comfyui`, `update_comfyui` and `get_logs` act on a comfy-cli *workspace*, and there is none on the host. `install_node` returns `unsupported: this ComfyUI install does not have ComfyUI-Manager at all`, so **T2 can't pass for comfy-mcp as configured**.
   - **Running it inside the container doesn't fix this.** I tested comfy-mcp over `docker exec -i`, in its own venv in the running container, with `VIRTUAL_ENV=/app/.venv`. comfy-cli then adopts `/app/ComfyUI` as its workspace and finds Manager, and `node_dependencies` works. Three things still block T2:
     - **Consent.** `install_node` always asks for consent through MCP elicitation, even with `confirm_install=true`. Headless `claude -p` answers "cancel", so an unattended agent can never install through comfy-mcp.
     - **Path.** With consent, comfy-cli installs into `<workspace>/custom_nodes` (`/app/ComfyUI/custom_nodes`). This image loads only `/app/custom_nodes` (`--base-directory /app`), and a pack installed there didn't load after a restart. Nothing reconciles the two without an image change. comfy-cli hardcodes the path, and cm-cli imports ComfyUI's `folder_paths` without arguments, so the base is the ComfyUI directory. ComfyUI has no environment override for its base directory. cm-cli's `--user-directory` (which would load `extra_model_paths.yaml`) isn't passed by comfy-cli. `COMFYUI_FOLDERS_BASE_PATH=/app` doesn't change the target. A symlink `/app/ComfyUI/custom_nodes → /app/custom_nodes` in the image would.
     - **Restart.** `restart_comfyui` only manages a ComfyUI that comfy-cli launched. Against comfy-cli 1.21.0 it fails at the stop step, because comfy-mcp 0.10.0 expects the error code `no_recorded_server` and comfy-cli returns `no_background_server`. Its "kill the untracked server holding the port" path, if reached with consent, would kill PID 1 and stop the container.
     
     The harness ships no in-container config for these reasons.
2. **As shipped, comfy-mcp's tool errors are masked.** A fresh install resolves `mcp` 2.2.0, which reports any non-`ToolError` exception as just `Error executing tool <name>`. comfy-mcp 0.10.0 was released before `mcp` 2.1 and 2.2, and main hasn't changed this. The harness pins `mcp==2.0.0`, where the real message comes through; `COMFY_MCP_SDK_VERSION=2.2.0` reproduces the shipped behaviour.
3. **comfy-mcp's `run_workflow` validates on the client side and never reaches `/prompt`.** So an agent sees comfy-cli's wording (`input 'images' expects IMAGE but LoadImage[1] produces MASK`), not ComfyUI's `return_type_mismatch`. T4 accepts either wording.
4. **artokun's `safe` preset withholds tools the tasks need.** It drops `create_workflow` (node info and validation), `install_custom_node`, `upload_image` and `queue`, leaving 16 tools where the full surface has 41. Under `safe`, T2 can't pass and T3 has no introspection tool. The evaluation uses the full surface. `safe` is what a shared deployment would ship, and `ARTOKUN_TOOL_PRESET=safe` restores it.
5. **Manager in this image refuses HTTP installs by default.** `startup.sh` passes `--listen`, which binds 0.0.0.0, and on a non-loopback listener Manager refuses installs unless its config sets `network_mode = personal_cloud`. That's any install through the Manager API, which is artokun's remote path. The harness binds loopback, which Manager treats as local.
6. **The `mcp:2.4.1` image starts** (the #110 fix holds). It has 17 tools and no `instructions`. It binds `0.0.0.0:9000` without authentication, so it runs only while its own runs do.
7. **As shipped, artokun can install into our container but can't restart it.** Against a loopback `COMFYUI_URL` it takes its local restart path, finds no process it launched, and returns `startup: not-attempted`. It uses the Manager reboot only for non-loopback targets.
   - **The fix.** Set `COMFYUI_RESTART_COMMAND` to a `curl` of Manager's `POST /v2/manager/reboot` (`ARTOKUN_MANAGER_RESTART=1`). That reboot re-execs ComfyUI in place as PID 1: the container keeps running, and `/system_stats` is back within seconds.
   - **Why curl exit 52 counts as success.** Manager drops the connection mid-reply, which is curl's exit 52, and the command treats that as success. artokun then reports `startup: confirmed`.
   - **Result.** With this setting, T2 passes.
   - **A shell-free alternative.** `COMFYUI_MCP_FORCE_REMOTE=1` treats the loopback target as remote, so artokun calls Manager's reboot itself. A probe confirmed the restart that way; no agent run has used it. It also turns off artokun's local-filesystem tools, which is arguably right for a container.
