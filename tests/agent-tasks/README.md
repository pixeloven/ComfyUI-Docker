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
./external.sh check T5 [--server artokun]   # the task's check.sh; appends a scorecard row for that server; exit 0 on PASS
                                            # (--batch LABEL marks it as one run of a set of repeats)
./external.sh summary T8 | compare A B      # repeats, read from baselines/ and results/: see *Repeating runs*
./external.sh down       # stop ComfyUI and every server; --purge also deletes what the harness created in $HARNESS_DATA
```

- **The brief** is what the lead hands the subagent, verbatim: a preamble, then the task's prompt. `up` prints it and writes it to `<workspace>/TASK.md`.
  - **The preamble is the same for every server.** It says "an MCP server", and names neither the server nor anything about reaching it: no URL (the server's or ComfyUI's), command, environment or token. Tool names will reveal the server anyway.
  - **The rules:** use only that server, through the client; no direct ComfyUI calls, no docker and no network; read only the workspace and run only the client; keep scratch files in the workspace and answers in its `results/`; and re-run a tool more narrowly rather than read a large result its own tooling saved elsewhere.
- **The client is the same for every server.** `servers/mcp_client.py` is stdlib only, and `up` installs a mode-0444 copy at `$HARNESS_DATA/bin/mcp_client.py`, outside the workspace, the repo and `tasks/`.
  - **What the agent runs:** `start`, `list`, `call <tool> '<json>'` (or `@file.json`) and `stop`, from the workspace. No agent hand-rolls JSON-RPC.
  - **The spec.** Beside the client, `up` writes `server.json`, also 0444, which tells the client how to reach this server:
    - **HTTP (comfyrelay, artokun):** the server's URL and a token file. The client never goes through a proxy, whatever the environment says, and sends the bearer token on every request, keeps the `Mcp-Session-Id` the server assigns, and reads replies as JSON or a server-sent event stream. The token files are `$HARNESS_DATA/.comfyrelay-token` and `.artokun-token`, mode 0600, outside the repo, `results/` and the workspace.
    - **stdio (comfy-mcp):** the command, environment and working directory from `servers/comfy-mcp.json`, plus `UV_OFFLINE=1`, because `up`'s probe has already filled uv's cache. The working directory is comfy-mcp's own `HOME` under `$HARNESS_DATA`. `COMFY_LOCAL_URL` reaches the server through this environment, never through the brief. The server gets only `PATH`, `TMPDIR` and the locale from the caller's environment, plus that list, so none of the operator's credentials reach it.
  - **One connection per task.** `start` runs a background broker that holds one connection, and for comfy-mcp one server process, across calls, since a server may keep state between them. `list`, `call` and `stop` talk to the broker over a Unix socket in the workspace.
  - **Hardening.** The broker rejects a malformed request without dropping the connection. `start` and `stop` clear a socket or pid file whose broker is gone. `up` and `down` stop any broker an agent left running.
  - **Logs.** No server's log is in the workspace. comfy-mcp's stderr goes to `$HARNESS_DATA/comfy-mcp.log`. The spec is readable, so no path in it points into `results/`, which holds the answer keys.
  - **The client's identity is the same for every server:** protocol 2025-06-18, and no client capabilities. It declares no elicitation capability, so comfy-mcp doesn't elicit consent. It takes its `confirm_install`/`confirm_spend` fallback, the tool's own confirm argument. A request a server sends anyway is answered as a headless client would answer it, so elicitation gets `cancel`.

  The workspace is the agent's working directory, and the prompt's `results/...` paths are relative to it. The prompt is copied, so the agent is never pointed at `tasks/`, where the answers are.
- **Confinement is by instruction only.** The subagent has the lead session's tools, Bash included, and is *told* to use only its server and the workspace. Nothing stops it reading `tasks/`, calling ComfyUI directly, or reaching the network. So an `external` row says the server *can* do the task, not that a confined agent did. The confined, blind run is `claude -p` (below).
- **The handoff.** `results/<server>-<task>.handoff.json` records the server, the brief, the client's spec, the workspace and the server's tools, for the lead.
- **Tasks.** T1, T3, T4, T5, T6-neutral and the tier-2 T7, T8, T9 and T10 (*Tier 2* below) run on every server. comfyrelay also gets T2-refuse, because it must not install, and the full T6, whose citations must be pages of its own docs index. artokun and comfy-mcp get T2 instead; `up` refuses the other pairings. T5's prompt names the relay's tools, so the other servers get `tasks/T5/prompt.neutral.md` ("use your MCP server's tools to find a template"), with the same check.
- **What `up` resets.** `up` can be repeated for the next task on the same instance; each one restarts the server. It also:
  - removes every handoff of this task, whatever its server, and writes the server's name to `<workspace>/.harness-server`. `check` refuses (exit 2) a `--server` the workspace wasn't set up for, so it can't score one server's run as another's.
  - empties the workspace and both servers' `HOME`s (`$HARNESS_DATA/artokun-home` and `comfy-mcp-home`). The package caches (`npm-cache`, `uv-cache`, `uv-python`) are kept.
  - removes a T2 pack an earlier install left on the volume, before anything reads ComfyUI (the ground-truth dump included), restarting ComfyUI only when there was one. Otherwise artokun's T2 pack would stay installed for every later task until the next T2 setup. It does this only on a `custom_nodes` the harness created (listed in `.harness-created`), never on an operator's own.
  - empties ComfyUI's queue: it clears pending prompts, interrupts the running one, and waits until nothing runs or waits (`HARNESS_QUEUE_TIMEOUT`, default 120 s), failing the `up` otherwise. A prompt an earlier run left queued would otherwise finish after setup and count as this task's work.
  - asks ComfyUI to drop its execution cache (`POST /free` with `free_memory`, which resets the cache, and `unload_models`). A graph an earlier task ran is then executed again instead of being served from the cache.

  ComfyUI's volumes and `/history` still carry over. Every check counts only what's new since its setup: `/history` entries, and for T1 and T5, output files that weren't there at setup. A run served from the cache reports the earlier file, so it fails.
- **Who owns a `HOME`.** `lib.sh` creates both `HOME`s, and lists them in `.harness-created`, before anything launches a server into them, `claude -p`'s comfy-mcp included. `up` empties only a `HOME` listed there, and refuses one it found instead; remove that yourself, or use another `HARNESS_DATA`. A `HARNESS_DATA` from before this change may hold such unlisted `HOME`s.
- **Reusing the instance.** `up` reuses a running core-cpu only when it runs the image `HARNESS_IMAGE` names now (compared by image ID, so a tag `build.sh` re-pointed doesn't match), on `HARNESS_DATA`, serving `COMFY_PORT`; it refuses otherwise. It runs `groundtruth.sh` whenever `HARNESS_RESULTS` has no dump yet, and T3's setup fails, rather than falling back to the committed answers, if there is still none.
- **T5's relay self-test.** T5's check ends by asking comfyrelay's `template_get` whether the chosen template is runnable (the run proved it is), and whether one that needs a model isn't.
  - **Scoring.** The verdict is reported separately on the detail line, and fails the task for comfyrelay only, where `template_get` is what the agent relied on. For artokun and comfy-mcp the task is scored on the run and the report alone, and a failed self-test is shown as not scored.
  - **Where the relay comes from.** For comfyrelay, the check asks the relay `up` started, which must still be running. For artokun and comfy-mcp, `check T5` starts a relay for the self-test only, after the agent has finished, and removes it afterwards.
- **Images.** `HARNESS_IMAGE` is the core-cpu to boot (default the local build from `build.sh`; `ghcr.io/pixeloven/comfyui/core:cpu-latest` works). T5's, T6's and T6-neutral's checks need `COMFYRELAY_IMAGE` whatever the server. `COMFYRELAY_IMAGE` is the relay under test (default `ghcr.io/pixeloven/comfyui/mcp:local`). Build it from the checkout with `IMAGE_LABEL=local docker buildx bake mcp --load`; on a host without a docker0 bridge, use `docker buildx build --network host` with the bake target's context, `skills` build context and args (`docker buildx bake mcp --print` lists them).
- **Isolation.**
  - **Network.** The containers run with `--network host`, and every server binds loopback. The relay refuses a port something already answers on.
  - **Several runs on one host.** Give each its own `HARNESS_CONTAINER` (the prefix of the container names), `COMFY_PORT`, `COMFYRELAY_PORT`, `ARTOKUN_PORT`, `HARNESS_DATA` and `HARNESS_RESULTS`. `HARNESS_RESULTS` holds the markers, derived answers and the scorecard, and defaults to `results/`. The token files, the client and the servers' `HOME`s and package caches live in `HARNESS_DATA`.
  - **Environment.** artokun, like comfy-mcp, is started with `env -i` and an explicit list, plus `PATH`, `TMPDIR` and the locale.
  - **Git.** Nothing a run writes is tracked by git: the default `results/` is gitignored.

### Before each release

Before each release, the lead session runs T1–T6 against comfyrelay, built from the release commit, with one subagent per task, and posts the scores on the release PR (#135). The subagents are confined by instruction only (above), so the scores are labelled that way.

1. For each task: `./external.sh up <task>`, then dispatch a subagent with the printed brief verbatim and the workspace as its working directory, then `./external.sh check <task> --tokens N --tool-calls N`, with the subagent's token and tool-call counts as the lead's harness reported them (comfyrelay is the default server for both).
2. `./external.sh down --purge`, and post every `external (not sandboxed)` row the release run appended to `results/scorecard.csv`, retries included, on the release PR.
3. Look for `ANSWER DRIFT` in the T3, T6 and T6-neutral rows. It means a derived answer no longer matches the committed `answers.json`, because ComfyUI or the docs moved; the row says which answers and how to accept them, in a PR of their own.

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
./external.sh up T6;        ./external.sh check T6           # the full T6, with citations, reported alongside
./external.sh up T6-neutral; ./external.sh check T6-neutral  # the one compared across servers

# artokun
./external.sh up T1 --server artokun; ./external.sh check T1 --server artokun
./external.sh up T2 --server artokun; ./external.sh check T2 --server artokun
./external.sh up T3 --server artokun; ./external.sh check T3 --server artokun
./external.sh up T4 --server artokun; ./external.sh check T4 --server artokun
./external.sh up T5 --server artokun; ./external.sh check T5 --server artokun
./external.sh up T6-neutral --server artokun; ./external.sh check T6-neutral --server artokun

# comfy-mcp (the client launches it, from the spec, when the agent runs `start`)
./external.sh up T1 --server comfy-mcp; ./external.sh check T1 --server comfy-mcp
./external.sh up T2 --server comfy-mcp; ./external.sh check T2 --server comfy-mcp
./external.sh up T3 --server comfy-mcp; ./external.sh check T3 --server comfy-mcp
./external.sh up T4 --server comfy-mcp; ./external.sh check T4 --server comfy-mcp
./external.sh up T5 --server comfy-mcp; ./external.sh check T5 --server comfy-mcp
./external.sh up T6-neutral --server comfy-mcp; ./external.sh check T6-neutral --server comfy-mcp

./external.sh down --purge
```

`check` takes the same `--server` as its `up`, and reads that run's handoff, `results/<server>-<task>.handoff.json`. Run each `check` before the next `up`, which removes this task's handoffs and empties the workspace the agent wrote its answers to. The brief is always `$HARNESS_DATA/workspace/TASK.md`.

Every server gets the same brief, the same client and a clean slate. What still makes the comparison uneven:

- **T5 depends on template tools.** artokun and comfy-mcp get a neutral prompt, and the check is the same for every server. Only comfyrelay's T5 also answers for the relay's own runnability verdicts (the self-test). comfy-mcp has template tools (`search_templates`, `get_template`'s `local_check`). artokun has none that reads ComfyUI's template index, so its agent has to find the template, and judge whether it runs, some other way.
- **Knowledge is compared on T6-neutral.** Every server, comfyrelay included, answers T6's q1, q2 and q4, graded on the answer alone (owner, 2026-10-03). q3 is about comfyrelay itself, so it's dropped.
  - **q1's docs answer is a typo.** docs.comfy.org's `specs/workflow_json.mdx` says `lastGroupid`, while ComfyUI's frontend and every template it serves say `lastGroupId`, next to `lastNodeId` and `lastLinkId`. So T6-neutral accepts either spelling, exactly. The second is derived at setup from the first served template that has the property, with q1's own pattern.
  - **The full T6 favours comfyrelay by construction.** Its citations must be pages of the relay's own docs index, so it keeps the docs spelling alone, and is reported alongside but not compared.
- **T2 differs by design.** comfyrelay is scored on refusing the install (T2-refuse), and the others on doing it (T2).
  - **comfy-mcp can't install here.** Per #102, its `install_node` acts on a local comfy-cli workspace and reports no ComfyUI-Manager on this instance (finding 1). With no elicitation capability declared, it relies on its `confirm_install` argument rather than asking for consent.
  - **artokun needs `ARTOKUN_MANAGER_RESTART=1`** to restart ComfyUI after its install (finding 7).

`claude -p` (`HARNESS_RUN=1 ./run.sh <server> <task>`) is the blind check: a fresh process with no lead session's context, given only its server's tools plus Read and Write in the workspace, and no Bash. Run it occasionally, for a comparison between servers; it needs the owner's approval.

## Tasks

| Task | The agent is asked to | `check.sh` passes when |
|---|---|---|
| T1 Workflow | Load `harness-input.png`, scale it to 256×256, invert it, and save it with prefix `t1_`. Built-in nodes only; no model needed. | A `/history` entry that's new since setup completed and has `ImageInvert`, and its `t1_*` PNG is new (not there at setup, so not served from ComfyUI's cache), 256×256 and bright on the left (the input is a black-to-white gradient). |
| T2 Node | Install ComfyUI-Custom-Scripts at commit `aac13aa7`, then evaluate `6 * 7` with `MathExpression\|pysssss`. | The class is in `/object_info`, the pack on the volume is the pinned commit (git `HEAD`, or registry version 1.2.5 when installed without `.git`), and a new `/history` entry used the class, completed and produced 42. `reset.sh` removes the pack and restarts ComfyUI. |
| T2-refuse Inverted T2 (#103) | The same request as T2, to a server that must not install (comfyrelay), plus writing what happened to `results/T2.json`: `installed`, `value` and `notes`. | Nothing was installed or restarted: the class isn't in `/object_info`, the `custom_nodes` volume matches what setup recorded, ComfyUI didn't restart (the container's `StartedAt` is unchanged and its log has no new `Starting server`, which also catches Manager's in-place reboot), and no new `/history` entry used the class. The report must be a JSON object with `installed: false` and a `value` key that is `null`; a claimed install or value fails. Setup runs T2's `reset.sh` first, so its own restart doesn't count. |
| T3 Introspection | Answer the 10 questions in `questions.json`, and write `results/T3.json`. | At least 9 of 10 match the answers `derive.sh` derives from this run's dump into `results/T3.answers.json` (the committed `answers.json` when there's no dump). The committed file is derived too, never written by hand; `derive.sh` reports where a new derivation differs from it, and never rewrites it. |
| T4 Failure | Submit `T4-workflow.json` unchanged, and report what happened in `results/T4.json`. | `succeeded` is `false`, `node_id` names the node ComfyUI rejected, and the report names the actual fault. ComfyUI's wording counts: its per-node error type or message, captured by setup from a real `/prompt` call. So does a client's own wording for the same fault: both types, MASK and IMAGE, plus "mismatch" or "expects". A success claim, or only the generic "Prompt outputs failed validation", fails. |
| T5 Template (#103) | A goal: a copy of an image at twice its width and height, from a workflow template. Choose one this instance can run with `template_search`, get it with `template_get`, run it unchanged with `workflow_run`, and write `results/T5.json`: `template`, `runnable` (as `template_get` said), `job_id` and `outputs`. Name only the files saved to `output/`, not temporary previews. Through `external.sh`, on every server. artokun and comfy-mcp get `prompt.neutral.md`, the same goal without comfyrelay's tool names, and the same check. | The template is one ComfyUI's `/templates/index.json` tags `Image Upscale`. Its job is a `/history` entry new since setup that completed, with the template's nodes and settings: the job runs each node class as many times as the template does (frontend-only nodes such as notes aside), and every value it sets on a node (every input that isn't a link; an empty dict or a null counts as unset, which is how a converter writes ImageCompare's display-only `compare_view`) is among the widget values of a template node of that class, so the input file, upscale method, factor and file prefix are the template's. Links aren't compared. Each output the index declares for it saved a new file (not there at setup) of that media type to `output/`, a PNG at twice the input's size; the report lists exactly those files and says `runnable: true`. Then a relay self-test, on the detail line: comfyrelay's `template_get`, asked by the check itself, says `runnable: true` for the template and `runnable: false`, with missing models, for the first candidate whose template declares a model. It fails comfyrelay's T5 only, never another server's. |
| T6 Knowledge (#134) | Answer the 4 questions in `prompt.md` from the relay's built-in docs (`docs_search`, `docs_guide`), and write `results/T6.json`: each id maps to `{answer, path}`, the path being the search result or guide the answer came from. One question is from the workflow JSON spec, one from the server's routes, one only this project's guides answer, and one from a tutorial. It's run by a subagent, not a billed `claude -p` (owner, #134), through `external.sh`. comfyrelay only; every server, comfyrelay included, runs T6-neutral for the comparison. | Every answer equals the one in `answers.json` as a whole, so a hedge such as "either X or Y" fails. Case counts where the question says so, and a route may drop its leading slash. Every cited path is a page in the image's own index where the question's pattern finds that same answer. `derive.sh` copies that index out of the relay image (`COMFYRELAY_IMAGE`, or its argument) to `results/T6-docs.sqlite` and derives `results/T6.answers.json` from it: each question names its page and a pattern, and the answer is what the pattern captures there. The committed `answers.json` is derived the same way, never written by hand, and `derive.sh` reports where a new derivation differs from it, so a docs bump that moves an answer shows up. |
| T6-neutral Knowledge, compared (owner, 2026-10-03) | Answer T6's q1, q2 and q4 (not q3, which is about comfyrelay) from whatever the MCP server can reach, and write `results/T6-neutral.json`: each id maps to `{answer, source}`, the source being a free-text note on where the answer came from, kept for the scorecard. Every server runs it, through `external.sh`. | Every answer equals an accepted answer as a whole, normalised as T6 normalises it: case counts for q1, and q2 may drop its leading slash. q1 accepts T6's docs answer, `lastGroupid` (a typo in the docs), or the spelling this instance's served templates use, `lastGroupId`, both derived at setup (`derive-t6-neutral`, into `results/T6-neutral.answers.json`). A hedge such as "either X or Y" fails. The `source` isn't checked, and a missing one is fine. Setup derives the key with `tasks/T6/derive.sh`, the same `results/T6.answers.json` that T6 uses, from the relay image. |
| T7 Author and tweak (tier 2, #212) | Start from one of the instance's text-to-image templates and adapt it to the installed SD 1.5 checkpoint: `a red apple on a wooden table`, 256×256, 4 steps, seed 1, prefix `t7_`; run it. Then change the seed to 2 and the width to 384, keep everything else, and run it again. | Two of the `/history` entries new since setup, in this order. The first completed and saved a new 256×256 `t7_` PNG from a `SaveImage` that has, upstream, the checkpoint, 4 steps, seed 1, and the prompt text on the conditioning that feeds a sampler's or guider's positive input, links followed. A later one did the same with seed 2 and a new 384×256 `t7_` PNG, and its `SaveImage` computes exactly what the first one's does once seed and width are left out (compared as T8 compares), so the second run may change nothing but the seed and the width. The positive input is `conditioning` on `BasicGuider`, `cond1` on `DualCFGGuider`, and `positive` on the samplers and every other guider in ComfyUI v0.38.0 (#220). A value a template routes through a backend `Primitive*` node (`PrimitiveInt`, `PrimitiveStringMultiline` and the like) counts as set where it is used. The graph's other nodes and values are the agent's choice, so any text-to-image template that runs on SD 1.5 can pass. Runs are ordered by their `execution_start`, or by `/history`'s order when one lacks it. |
| T8 Fix a broken graph (tier 2, #212) | `T8-workflow.json` is an SD 1.5 txt2img graph in API format with four faults: a misspelled checkpoint name, a missing required input (`EmptyLatentImage.height`), a COMBO value that isn't one (`sampler_name: "eular"`), and a CLIP output wired into `VAEDecode`'s VAE input. The prompt states the intent (256×256, the SD 1.5 checkpoint, the euler sampler, prefix `t8_`), so each fault has one fix. Fix only what is broken, run it to completion. | A `/history` entry new since setup ran the intended graph, completed, and saved a new 256×256 `t8_` PNG. "The intended graph" is compared by what each `SaveImage` computes: its class, its set values (7 and 7.0 are the same) and, recursively, the nodes and output slots its links come from, whatever the node ids are. Extra nodes are allowed; a changed value or link fails. Setup submits the broken graph once and fails unless ComfyUI reports all four faults. The detail counts the runs since setup. The numbers to compare are the scorecard's `mcp_runs` (the submissions it took) and `mcp_work_calls` (the MCP calls, polling aside). |
| T9 Edit a saved workflow (tier 2, #212) | `t9-portrait.json`, which setup saves among the user's workflows through `/userdata` (UI format, 512×768, 20 steps, prefix `portrait`), must render at 256×384 with 4 steps and the prefix `t9_`, keep everything else, be saved back under the same name in the same format, and run once. | `workflows/t9-portrait.json` read back from `/userdata` is still the UI format (`nodes` and `links` lists), with the same nodes and links (link ids aside) and every widget value as setup saved it except those three; and a `/history` entry new since setup ran that edited workflow (compared as T8 compares), completed and saved a new 256×384 `t9_` PNG. |
| T10 Make a workflow runnable (tier 2, #213) | Two workflows in the workspace with different needs, so nothing found in one answers the other. `T10-ui.json` (UI format, an SDXL txt2img): a missing checkpoint (`sd_xl_base_1.0.safetensors`) and VAE (`sdxl_vae.safetensors`), each with its Hugging Face URL and sha256 in `properties.models`; `ConstrainImage\|pysssss` from the registry pack `comfyui-custom-scripts` (`cnr_id`, `ver` 1.2.5); `GetImageSizeAndCount` from the git pack `kijai/ComfyUI-KJNodes` (`aux_id`, `ver` a commit), inside a subgraph; and a LoRA named bare that is on disk only as `sdxl/<name>`. `T10-api.json` (API format, an SDXL Turbo graph with an upscale): a missing checkpoint (`sd_xl_turbo_1.0_fp16.safetensors`) with no source in the workflow, which the stock template `sdxlturbo_example` declares (and so does Manager's bundled model list; see *T10's setup*); a missing LoRA (`add-detail-xl.safetensors`) that nothing declares; `ImageResizeKJv2`, from the same git pack; and an upscaler named bare that is on disk only as `esrgan/<name>`. Without installing, downloading or running anything, write `results/T10.json`: per workflow, `missing_models`, `missing_node_classes` and `model_value_changes` (`from`, `to`); `comfy_yaml_models`, entries for `comfy.yaml`'s `models` list, valid against `comfy.schema.json`, which setup puts in the workspace, for each missing model with a declared source; and `custom_nodes`, in ComfyUI-Manager's snapshot shape (`git_custom_nodes` by URL, with `hash` and `disabled`, and `cnr_custom_nodes` by registry id, with the version). Then write both workflows back with their model value fixed, in their own formats, as `results/T10-api.json` and `results/T10-ui.json`. | Only what the agent wrote, and the instance's state, are graded; the transcript isn't read. For each workflow (keyed by file name, with or without `.json`), each list is exactly what it needs: the UI graph 2 missing models, 2 classes and the LoRA's change, the API graph 2 missing models (the undeclared LoRA included), 1 class and the upscaler's change. `results/T10-api.json` is the original with only the upscaler's value changed (7 and 7.0 the same, `_meta` ignored), and `results/T10-ui.json` is still the UI format, with the same nodes, links (link ids aside) and subgraph, and every widget value as setup wrote it but the LoRA's. `comfy_yaml_models` passes comfyctl's own validation (the bundled schema, then its semantic checks) and installs exactly the three missing models with a declared source, each into its folder (`models/checkpoints/` or `models/vae/`): no entry for the undeclared LoRA. Each comes from `hf:<repo>` (`file` the model, at `main` or no revision) or from the declared URL itself (with or without `?download=true`), and a URL source must state the file's `sha256`, as `comfyctl fetch resolve` requires. `git_custom_nodes` is exactly `https://github.com/kijai/ComfyUI-KJNodes` (case, a trailing `/` or `.git` aside), with the full commit as `hash` and `disabled: false`, and `cnr_custom_nodes` is exactly `{"comfyui-custom-scripts": "1.2.5"}`. And the instance is as setup left it: no `/history` entry since setup, none of the classes in `/object_info`, nothing new in the `custom_nodes` volume or under `models/`. |

**Why that node pack.** [ComfyUI-Custom-Scripts](https://github.com/pythongosssss/ComfyUI-Custom-Scripts) (pysssss) is MIT-licensed, has about 3.2k stars and is maintained. Its backend is pure Python with no `requirements.txt`, and its registry entry lists no dependencies. `MathExpression|pysssss` is an output node, so a one-node workflow runs it on CPU. The pin, `aac13aa7`, is the commit that registry version 1.2.5 was published from, so a git install and a Manager or registry install are the same code. The smaller alternative I checked, ComfyUI-Logic, is archived and has no license.

**Why these T3 questions.** They come in near-identical pairs that differ in exactly one value: `VAEDecodeTiled` vs `VAEEncodeTiled` `tile_size` step (32 vs 64), and `ImageScaleBy` vs `LatentUpscaleBy` `scale_by` (1.0 vs 1.5). Others have defaults a model tends to remember wrongly: `EmptyLatentImage` width is 1024 on v0.37.0, not 512. Scoring ignores the order of option lists but not output order, and accepts `"1.0"` for `1.0`.

**Why T5's goal and setup.** core-cpu has no models, and of the 564 templates ComfyUI v0.37.0 serves (`comfyui-workflow-templates` 0.11.66), 5 need none and use no partner-API node. Four of them load an example image that ComfyUI doesn't serve, and one of those upscales: `utility_interpolation_image_upscale` (LoadImage, ImageScaleBy by 2 with lanczos, SaveImage), so the goal is an upscale.
- **Setup** gives every template tagged `Image Upscale` (23 at 0.11.66) the input images its index entry names (`io.inputs`), as 512×384 stand-ins. That leaves models, nodes and partner APIs to decide which can run, which is what the relay's runnability check is for, without downloading a model.
- **What it tests.** A search for the goal returns model-based upscalers too (SeedVR2, Z-Image), so the agent has to choose by runnability rather than rank.
- **What's derived.** The candidates, their inputs and each one's output media type come from the live index. The template's node classes and widget values come from its own `/templates/<name>.json`, so a hand-built graph with another method or prefix fails. The runnability comes from the relay at check time, for the chosen template and for a candidate that declares a model. The outcome comes from `/history` and the output file on disk.
- **What's written by hand.** Only the goal: the `Image Upscale` tag, the factor 2 and the stand-in's size, in `harness.py`.
- **If templates change.** A template bump that adds a runnable upscaler is still a pass. One that removes it leaves no runnable answer, and T5 fails until its goal changes.

## Tier 2: workflow development (#212)

T1–T6 use no model and are single-shot, and they have passed 6/6 on every release since 5.1.0, so they can't show whether a workflow-development feature helps. T7–T10 can: T7–T9 each run a real checkpoint on CPU over several steps, T10 prepares two workflows that can't run yet, and each is the baseline for later work, which must cite the task it improved (#201, D6 and D8):

| Task | Baseline for | Number to beat | `baseline-6.0.0` |
|---|---|---|---|
| T7 Author and tweak | authoring in general: the relay polish (#217) | `mcp_work_calls` | 5/5 passes, 15 (13–17) work calls |
| T8 Fix a broken graph | the requirements report (#213) and the dry run (#215). Today's `workflow_validate` checks neither input types nor values, and called the broken graph runnable in every baseline run. So agents check each input themselves before submitting (`node_describe` ×3 and `model_list` in each run), and all 5 submitted once. The target is those work calls, not the submissions: `mcp_runs` was 1 every time | `mcp_work_calls` | 5/5 passes, 9 (7–9) work calls |
| T9 Edit a saved workflow | saved workflows (#216): today's relay has no tool that reads or writes ComfyUI's user data, so T9 is expected to fail until it does | passes | 0/5 passes |
| T10 Make a workflow runnable | the requirements report (#213). T8 can't show it (owner, 2026-10-17): T8's faults are values and types, which ComfyUI checks at `/prompt`, and in #228's T8 runs the agents checked them by hand whatever the report said. T10's needs are what the report is for, and there are enough of them, in enough folders and pack kinds, for a report to save calls | `mcp_work_calls` | not run: T10 came later, and its arms are interleaved in one session (*Repeating runs*) |

Each task's number to beat is named in advance, and `compare` judges only that one (*Repeating runs*). The baseline is `baselines/baseline-6.0.0.csv`: 5 runs per task on main's images at `b6c7701e`, recorded in #222.

They aren't part of the release run (*Before each release*). Run them like any other task, through `external.sh`, and 5 times per arm for a result anyone will cite (*Repeating runs*); T7, T9 and T10 need a relay that converts UI-format workflows (`COMFYRELAY_IMAGE` set to an `mcp-convert` image), since templates, saved workflows and T10's second workflow are UI format, and T8 runs on `mcp`.

**T10's setup.**
- **What the instance lacks is read from ComfyUI.** Setup puts the two placeholders in place, then fails unless `/object_info` has none of the three classes, `/models/<folder>` lists none of the four missing models and lists each placeholder under its subfolder only, and the stock template `sdxlturbo_example` still declares the API graph's checkpoint. It writes both workflows to the workspace and to `results/T10.setup.json`, with the `custom_nodes` volume's entries and the files under `models/`, which the check compares against.
- **Each need is determinable from the files and the instance.** The UI graph declares its models' URLs and hashes and its packs. The API graph's checkpoint is declared by a stock template on the instance; its LoRA by nothing, so it is reported and not fetched.
- **Manager's model list declares some of them too.** The image bundles ComfyUI-Manager's `model-list.json` (`comfyui_manager/model-list.json`), which lists the turbo checkpoint, the SDXL base, `sdxl_vae` and the offset LoRA with the same Hugging Face URLs, under subfolders (`checkpoints/SDXL-TURBO/`, say). It lists neither `add-detail-xl.safetensors` nor `RealESRGAN_x4plus.safetensors`, so the LoRA stays undeclared. On this instance its route, `/v2/externalmodel/getlist`, belongs to Manager's legacy server and answers 404, so an agent reaches the list only through a server that reads it. Either way, the grading wants each model where the workflow names it, at the top of its folder, not under the list's subfolder. Its class, `ImageResizeKJv2`, is the KJNodes pack's, whose source the UI graph declares, so `custom_nodes` is the same two packs either way. The brief says to take a source only from what the workflows or the instance declare.
- **The placeholders** (`loras/sdxl/` and `upscale_models/esrgan/`) are valid safetensors files with no tensors, 16 bytes, so ComfyUI lists them and a metadata read can parse them, though nothing can load them. T10 runs nothing. Every other task's setup removes them (`harness.py t10-clean`), so T7's "one model installed" still holds, and `down.sh --purge` removes them from a `models/` the harness found too. Neither removes a file that isn't byte for byte a placeholder. Only `down.sh --purge`, once ComfyUI has stopped, removes the directories setup made for them, and only when they're empty: ComfyUI v0.38.0 caches each model directory it has listed, and once one is gone, `/object_info` answers 500 until it's back.
- **The sources are real.** Every URL answers, the hashes are Hugging Face's own sha256 for each file, `ImageResizeKJv2` and `GetImageSizeAndCount` exist at the KJNodes commit, and `ConstrainImage|pysssss` at registry version 1.2.5 (commit `aac13aa7`, T2's pin). Nothing in the task fetches them. The `hf:` revision must be `main` or unset, since every declared URL says `main`.
- **The comfy.yaml entries are validated by comfyctl,** which owns the format: its `schema.validate` and `validate_semantics`, and its `install_path` for where each file lands. The check runs them through `uv` in `services/`, as the tier-2 setups run `comfyctl fetch`.
- **Fair to any server.** The brief names no tool. It gives the manifest's schema and describes the snapshot shape, since no other server knows this repo's manifest. A server's own proposals help only if the agent can use them.

**Saved workflows don't carry over.** Each tier-2 setup empties `user/default/workflows/` when the harness created the `user` volume, so T9's edited file, say, can't help a later T7. On a `user` volume the harness found, it removes only T9's own file and leaves the operator's workflows alone.

**The model.** Each tier-2 setup fetches Stable Diffusion 1.5 (`v1-5-pruned-emaonly-fp16.safetensors`, 2.13 GB, from [Comfy-Org/stable-diffusion-v1-5-archive](https://huggingface.co/Comfy-Org/stable-diffusion-v1-5-archive), ungated) into `$HARNESS_DATA/models/checkpoints/`. The licence is CreativeML OpenRAIL-M: redistribution and commercial use are allowed, with use-based restrictions that any copy must carry.
- **How it's fetched.** `models/comfy.yaml` declares it, and `models/comfy-lock.yaml` pins it by commit and sha256. Setup runs this repo's own `comfyctl fetch fetch` on that lock (through `uv run` in `services/`, or the comfyctl executable `COMFYCTL` names), which verifies the hash and skips a file already there. Regenerate the lock with `comfyctl fetch resolve` (the command is in `models/comfy.yaml`). It needs `uv` on the host and no token. `down.sh --purge` deletes it with the rest of a harness-made `models/`; on a `models/` the harness found rather than made, the file is added and left there.
- **Why not a tiny model.** No "tiny" SD checkpoint on Hugging Face loads in ComfyUI's stock `CheckpointLoaderSimple`. The single-file conversions of distilled SD 1.5 models (`turingevo/tiny-sd-safetensors`, 1.06 GB, and `ckpt/bk-sdm-tiny-2m`, the same size and a safetensors file named `.ckpt`) fail to load with size mismatches in `output_blocks`. The originals (`segmind/tiny-sd`, `nota-ai/bk-sdm-tiny`) are diffusers folders, whose U-Nets match none of the diffusers configs ComfyUI's `UNETLoader` recognises (read from `comfy/model_detection.py`, not tried). `IDKiro/sdxs-512-dreamshaper` should match one of them (`SD_XS`), but it comes as three files for three loaders, 1.76 GB in fp32, and isn't smaller in practice. Random-weight test models (`hf-internal-testing/*`) weren't tried: their 32-channel U-Nets match none of ComfyUI's model configs. SD 1.5 at fp16 is the smallest checkpoint found that the stock nodes load.
- **What it costs.** On the 8-core CPU these baselines ran on, a 256×256, 4-step run takes about 16 s with the model load and 11 s warm, and 512×512 at 20 steps takes about 4 minutes. That's why every tier-2 prompt asks for small images and few steps.
- **No template names it.** ComfyUI v0.38.0's template index has no SD 1.5 text-to-image template, so T7's agent has to adapt one made for another model (an SDXL one, say) to the checkpoint it has. That's part of the task.

## Repeating runs (#221)

One run of a tier-2 task says little. In #218's two T8 baselines, the same agent model on the same relay image took 7 MCP calls, polling aside, and then 4. To claim a feature improved a task, repeat it. The rule is the owner's (2026-10-16):

- **Run 5 times per arm.** Run the baseline and the feature 5 times each, on the same core-cpu image digest, test model, host and agent model. Only the relay image under test differs between them.
- **Interleave the arms in one session** (owner, 2026-10-17): A, B, A, B and so on, switching the relay image between runs. Never run one arm after the other, and never compare an arm with a batch from another session. In #228's T8 runs, the control runs on the baseline images took 4 MCP calls, below `baseline-6.0.0`'s 7–9: a session can move the number by more than the feature does. Interleaving gives both arms the same drift.
- **An improvement needs two things.** B's median must be better than A's, **and** the two arms' runs must mostly not overlap. At 5 per arm, full separation is the strongest result possible (one-sided Mann–Whitney p ≈ 0.004).
- **Pass rates.** 0/5 against 5/5 is conclusive. Anything in between needs about 10 runs per arm.
- **One number per task, named in advance.** Judging four numbers at once raises the chance of a false "improved" from about 4% to about 14%. So each task is judged on its *number to beat* (*Tier 2*: `mcp_work_calls` for T7, T8 and T10, passes for T9), and the other numbers are context.

**The baseline's images.** `baselines/baseline-6.0.0.csv` ran on main's images at `b6c7701e`. main's core has changed since: #219 added the node venv. To run on those exact images, pull them by digest. `up` never pulls: it builds a core-cpu it can't find, and the relay script refuses one it can't find.

```sh
docker pull ghcr.io/pixeloven/comfyui/core@sha256:2c2f8b3aab9a979d845ab6946be4062e8cc71127a2377449b7d781898e39cd49
docker pull ghcr.io/pixeloven/comfyui/mcp@sha256:e0966b96aa8d8a1fc7ee5ec86725ad72275117cbccb7189d14d233992cf01847
docker pull ghcr.io/pixeloven/comfyui/mcp-convert@sha256:1d463665cd2a9896784b9c49bdcb1565a822988d84b2273d88721b35241903b0

export HARNESS_IMAGE=ghcr.io/pixeloven/comfyui/core@sha256:2c2f8b3aab9a979d845ab6946be4062e8cc71127a2377449b7d781898e39cd49
# T7, T9 and T10:
export COMFYRELAY_IMAGE=ghcr.io/pixeloven/comfyui/mcp-convert@sha256:1d463665cd2a9896784b9c49bdcb1565a822988d84b2273d88721b35241903b0
# T8:
export COMFYRELAY_IMAGE=ghcr.io/pixeloven/comfyui/mcp@sha256:e0966b96aa8d8a1fc7ee5ec86725ad72275117cbccb7189d14d233992cf01847
```

A feature arm keeps that `HARNESS_IMAGE` and sets `COMFYRELAY_IMAGE` to the relay under test. When the feature needs a newer core, it needs a new baseline on that core too.

**How to run the arms.** Give every run of an arm one label with `--batch`, run each with a fresh subagent, and alternate the arms by setting `COMFYRELAY_IMAGE` for each `up`:

```sh
A=ghcr.io/pixeloven/comfyui/mcp-convert@sha256:...   # the baseline's relay, by digest
B=ghcr.io/pixeloven/comfyui/mcp-convert:w1a          # the relay under test
for i in 1 2 3 4 5; do
  COMFYRELAY_IMAGE=$A ./external.sh up T10 --batch control-213
  # dispatch one fresh subagent with the brief, verbatim; note its tokens and tool calls
  ./external.sh check T10 --batch control-213 --tokens N --tool-calls N
  COMFYRELAY_IMAGE=$B ./external.sh up T10 --batch w1a-213
  # dispatch another fresh subagent
  ./external.sh check T10 --batch w1a-213 --tokens N --tool-calls N
done
./external.sh compare control-213 w1a-213 --task T10
```

- **Switching is one variable.** Each `up` stops the relay and starts it again from `COMFYRELAY_IMAGE`, while ComfyUI keeps running on the same `HARNESS_DATA`, so the arms need no `down` between them. `up` reuses ComfyUI only if it runs `HARNESS_IMAGE`, so the core can't change between arms either. `up` prints the relay it started (`== relay: <reference> (<image ID>)`) and records the image ID in the handoff.
- **A batch is one relay image per task.** The first comfyrelay run of a task that `check --batch L` records writes its relay's image ID to `results/batches/L.<task>.relay-image`. `check` then refuses (exit 2) a run of that task under L on another image, before scoring it, so a run whose image was switched and label wasn't (or the reverse) can't join the wrong arm. Per task, because one label can span relays: `baseline-6.0.0` ran T8 on `mcp` and T7 and T9 on `mcp-convert`. `up --batch L` makes the same check before an agent is dispatched. To reuse a label for another image on purpose, remove that file.

- **Labels.** A label is letters, digits, `.`, `_` and `-`. Name it after what the arm runs (`dryrun-215`). `check` refuses (exit 2) the label of a committed baseline (`baselines/<label>.csv`), so a control run can't join `baseline-6.0.0`.
- **Digests.** Record each arm's image digests where you report it. The scorecard has the label, not the digests.
- **The baseline arm runs again.** A committed baseline (`baselines/*.csv`) records one session. It is the number a task started from, not an arm to judge a new session's runs against. Run its images again as arm A, label it e.g. `control-213`, and judge B against that. `compare baseline-6.0.0 control-213` then shows how far this session sits from the recorded one, as context.

**How to read the arms:**

```sh
./external.sh summary T8 [--batch dryrun-215] [--server comfyrelay] [--scorecard PATH]...
./external.sh compare baseline-6.0.0 dryrun-215 [--task T8] [--server comfyrelay] [--metric M] [--scorecard PATH]...
```

- **What both read.** Both read the committed baselines (`baselines/*.csv`) and this `HARNESS_RESULTS`'s scorecards (`scorecard.csv`, plus the `scorecard.before-*.csv` files set aside when its columns changed), plus every `--scorecard` given.
  - A row that appears in two files counts once.
  - A batch whose rows come from files with different columns gets a warning on stderr, since a column one file lacks reads as no value there.
  - Neither command writes anything, and neither starts or creates anything in `HARNESS_DATA`.
- **Passing runs only.** Passes are counted over every run. The other numbers come from passing runs only, because a run that gives up early is cheap: counting it would read a drop in passes as fewer calls.
- **`summary`** prints a Markdown table with one line per server and batch. It shows k/N passes, then the median and (min-max) of `mcp_work_calls`, `mcp_runs`, `tokens` and `seconds` over the passing runs.
  - When some passing runs didn't record a number (`--tokens` not passed, say), the cell says how many runs it covers.
  - An unlabelled run counts under `(none)`, and a `dry-run` row doesn't count at all.
- **`compare`** prints a table for each task and server that has runs in both batches. Each number gets A's and B's median (min-max).
  - **What it judges.** Only the task's number to beat, or `--metric` (`passes`, `mcp_work_calls`, `mcp_runs`, `tokens` or `seconds`), gets a verdict. The others say `context`. A task with no number named is judged on passes.
  - **The verdict line.** The table ends with `verdict on <number>: …`.
  - **How far apart.** "Pairs apart" counts the (A, B) run pairs on the side B's median moved to, ties counting half. That count is the Mann–Whitney U, so 25/25 at 5 per arm means no overlap. Beside it is the exact one-sided p-value, computed over every way to split the pooled runs between the two arms.
  - **The verdict.** It reads `improved: the medians differ and the runs don't overlap` (or `mostly don't overlap`) when the median is better and p ≤ 0.05. At 5 per arm, that means at least 21 of the 25 pairs. When the median is worse instead, it reads `worse: …`.
  - **When it's inconclusive,** it gives the reason: the medians are the same, the runs overlap, or an arm has fewer than 5 runs. For a number other than passes, the reason can also be fewer than 5 *passing* runs in an arm (`inconclusive: needs 5 passing runs per arm`), with `the pass rates differ` added when they do.
  - **A lower pass rate blocks the other numbers.** When B passes less often than A, every other number reads `inconclusive: the pass rate dropped (judge passes first)`, however its passing runs compare. Otherwise an arm topped up until 5 runs pass (5 of 10, say) could show cheaper passing runs as an improvement.
  - **Pass rates.** None against all is conclusive at 5 per arm. A rate in between is judged, by the same test (here, Fisher's exact test), only when both arms have 10 runs.
- **Compare within one server only.** `mcp_runs` counts `workflow_run` calls and `mcp_work_calls` leaves out `job_status`, which are comfyrelay's tool names. Another server's submissions and polling go by other names, so its `mcp_runs` is 0 and its polling counts as work. `compare` never sets one server against another, and its numbers aren't comparable across servers.

## Recording scores

`run.sh` and `external.sh check` append one row per run to `results/scorecard.csv`, with these columns: `timestamp, server, task, result, detail, seconds, mode, turns, cost_usd_notional, tokens, tool_calls, mcp_calls, mcp_work_calls, mcp_runs, mcp_errors, mcp_by_tool, batch`. A scorecard with other columns is renamed `scorecard.before-<time>.csv` rather than appended to.

- **`tokens` and `tool_calls`** are what the lead's harness reported for an external agent, passed to `external.sh check` as `--tokens` and `--tool-calls`. They are empty when not passed, and for `run.sh`.
- **The `mcp_*` columns** come from the harness's client, so they don't depend on the agent's own report. The broker appends one line per request it forwards (the method, the tool, whether it failed and how long it took, never the arguments or the result) to `$HARNESS_DATA/mcp-calls.jsonl`, which the spec names and each `up` empties. A line that doesn't parse is skipped, and a logging failure never fails the call. `check` prints the summary too.
  - `mcp_calls`: every `tools/call`, polling included.
  - `mcp_work_calls`: the same without polling (`job_status`), which counts how long the agent waited, not how many steps it took. This and `mcp_runs` are the numbers a later feature should lower.
  - `mcp_runs`: the `workflow_run` submissions.
  - `mcp_errors` and `mcp_by_tool`: how many calls failed, and a count per tool, polling included.
- **`batch`** is the label `external.sh check --batch` gave the run, which `summary` and `compare` group repeats by (*Repeating runs*). It is empty when none was given, and for `run.sh`.

`mode` is one of:

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
