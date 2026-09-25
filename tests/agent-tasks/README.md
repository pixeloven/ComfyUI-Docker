# MCP evaluation harness (Phase 1)

This harness scores three MCP servers on what an agent actually gets done against this repo's pinned `core-cpu` image. It is Phase 1 of #100, tracked in #102. Each task pairs a prompt with a check script, and every check verifies the outcome through ComfyUI's HTTP API or the filesystem. No check reads an agent transcript.

Each server runs in the best reasonable configuration, the owner's call on #102. What each one does as shipped is recorded under *Findings*.

| Server | How it runs here | Config |
|---|---|---|
| [Comfy-Org/comfy-mcp](https://github.com/Comfy-Org/comfy-mcp) | stdio, `uv run` with `comfy-mcp==0.10.0`, `comfy-cli==1.21.0` and `mcp==2.0.0`, so real errors come through (finding 2) | `servers/comfy-mcp.json` |
| [artokun/comfyui-mcp](https://github.com/artokun/comfyui-mcp) | streamable HTTP on `127.0.0.1:9100/mcp`, `npx comfyui-mcp@0.52.203`, full tool surface. The bearer token stays required, and auto-update and panel auto-install stay off. | `servers/artokun.json` and `artokun.sh` |
| [joenorton/comfyui-mcp-server](https://github.com/joenorton/comfyui-mcp-server) | streamable HTTP on `:9000/mcp`, from `ghcr.io/pixeloven/comfyui/mcp:2.4.1`, pinned by digest | `servers/joenorton.json` and `joenorton.sh` |

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

- **Instance.** `up.sh` runs the image with `--network host`, Manager on, and every data volume under `$HARNESS_DATA` (default `/tmp/comfyui-harness`). It adds `CLI_ARGS=--listen 127.0.0.1`; see finding 5.
- **artokun restart.** `ARTOKUN_MANAGER_RESTART=1` lets artokun's `restart_comfyui` reboot ComfyUI through Manager's `POST /v2/manager/reboot`. It is set through `COMFYUI_RESTART_COMMAND`, as a `curl` to that endpoint, and gives artokun no Docker access. Off by default, so the scored baseline stays as shipped; see finding 7.
- **Other knobs.** `HARNESS_MODEL` (default `claude-opus-5-5`, pinned so every run is comparable), `HARNESS_TIMEOUT` (default 900 s) and `HARNESS_BUDGET_USD` (default 5 per run, a runaway guard only). `HARNESS_BARE=1` adds `--bare`, which also skips CLAUDE.md and user memory, but it needs `ANTHROPIC_API_KEY`.
- **The agent's sandbox.** The agent runs as `claude -p --restricted --tools Read,Write`, with only its server's tools allowed and `--permission-mode dontAsk`. It has no Bash, so it can't reach ComfyUI except through the MCP server. Its working directory is `$HARNESS_DATA/workspace`, which holds only the task's inputs, so it can't read `answers.json` or the ground-truth dump. Output is `stream-json`, so the transcript records every tool call.

## Tasks

| Task | The agent is asked to | `check.sh` passes when |
|---|---|---|
| T1 Workflow | Load `harness-input.png`, scale it to 256×256, invert it, and save it with prefix `t1_`. Built-in nodes only; no model needed. | A `/history` entry that's new since setup completed and has `ImageInvert`, and its `t1_*` PNG is 256×256 and bright on the left (the input is a black-to-white gradient). |
| T2 Node | Install ComfyUI-Custom-Scripts at commit `aac13aa7`, then evaluate `6 * 7` with `MathExpression\|pysssss`. | The class is in `/object_info`, the pack on the volume is the pinned commit (git `HEAD`, or registry version 1.2.5 when installed without `.git`), and a new `/history` entry used the class, completed and produced 42. `reset.sh` removes the pack and restarts ComfyUI. |
| T3 Introspection | Answer the 10 questions in `questions.json`, and write `results/T3.json`. | At least 9 of 10 match `answers.json`. That file is derived from the dump by `derive.sh`, never written by hand. |
| T4 Failure | Submit `T4-workflow.json` unchanged, and report what happened in `results/T4.json`. | `succeeded` is `false`, `node_id` names the node ComfyUI rejected, and the report names the actual fault. ComfyUI's wording counts: its per-node error type or message, captured by setup from a real `/prompt` call. So does a client's own wording for the same fault: both types, MASK and IMAGE, plus "mismatch" or "expects". A success claim, or only the generic "Prompt outputs failed validation", fails. |

**Why that node pack.** [ComfyUI-Custom-Scripts](https://github.com/pythongosssss/ComfyUI-Custom-Scripts) (pysssss) is MIT-licensed, has about 3.2k stars and is maintained. Its backend is pure Python with no `requirements.txt`, and its registry entry lists no dependencies. `MathExpression|pysssss` is an output node, so a one-node workflow runs it on CPU. The pin, `aac13aa7`, is the commit that registry version 1.2.5 was published from, so a git install and a Manager or registry install are the same code. The smaller alternative I checked, ComfyUI-Logic, is archived and has no license.

**Why these T3 questions.** They come in near-identical pairs that differ in exactly one value: `VAEDecodeTiled` vs `VAEEncodeTiled` `tile_size` step (32 vs 64), and `ImageScaleBy` vs `LatentUpscaleBy` `scale_by` (1.0 vs 1.5). Others have defaults a model tends to remember wrongly: `EmptyLatentImage` width is 1024 on v0.37.0, not 512. Scoring ignores the order of option lists but not output order, and accepts `"1.0"` for `1.0`.

## Recording scores

`run.sh` appends one row per run to `results/scorecard.csv`, with these columns: `timestamp, server, task, result, detail, seconds, mode, turns, cost_usd_notional`. `mode` is `agent` or `dry-run`, and only `agent` rows count. `cost_usd_notional` is the figure `claude` reports; on a subscription the run uses plan quota, not money. The transcript goes to `results/runs/<server>-<task>.jsonl`, and whatever the agent wrote goes beside it.

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
