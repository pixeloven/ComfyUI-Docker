#!/usr/bin/env bash
# Run a task against comfyrelay with an agent the harness doesn't launch: a
# subagent of the lead session, given only the relay's tools. Three commands,
# so the lead can dispatch the agent between them:
#
#   ./external.sh up <task>       boot core-cpu if it isn't running (up.sh, then
#                                 groundtruth.sh), reset the task (its setup.sh),
#                                 start comfyrelay, and write and print the
#                                 handoff: results/<task>.handoff.json
#   (the agent does the task, and writes its results under the workspace)
#   ./external.sh check <task>    run the task's check.sh, append a row with mode
#                                 "external" to results/scorecard.csv, exit 0 on PASS
#   ./external.sh down [--purge]  stop ComfyUI and the relay (down.sh)
#
# Tasks: T1, T2-refuse, T3, T4, T5, T6. `up` can be repeated for the next task
# on the same instance; each one restarts the relay.
#
# The images: HARNESS_IMAGE (core-cpu, default the local build from build.sh;
# e.g. ghcr.io/pixeloven/comfyui/core:cpu-latest) and COMFYRELAY_IMAGE (default
# comfyrelay:latest, the image under test, built locally). Both containers use
# --network host and bind loopback. For several runs on one host, give each its
# own HARNESS_CONTAINER (the prefix of both container names), COMFY_PORT,
# COMFYRELAY_PORT, HARNESS_DATA and HARNESS_RESULTS.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

usage() { sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }

cmd="${1:-}"
case "$cmd" in
  up|check)
    task="${2:-}"
    [ -n "$task" ] || usage
    [ -f "$HARNESS_DIR/tasks/$task/prompt.md" ] || { echo "no task $task" >&2; exit 2; }
    handoff="$RESULTS/$task.handoff.json"
    ;;
  down) shift; exec "$HARNESS_DIR/down.sh" "$@" ;;
  *) usage ;;
esac

if [ "$cmd" = up ]; then
  if [ "$(docker inspect -f '{{.State.Running}}' "$HARNESS_CONTAINER" 2>/dev/null)" != true ]; then
    "$HARNESS_DIR/up.sh" >/dev/null
    "$HARNESS_DIR/groundtruth.sh" >/dev/null
  fi
  rm -f "$handoff"
  prepare_task "$task"
  "$HARNESS_DIR/servers/comfyrelay.sh" up

  # The token may come from the environment; the agent reads it from a file.
  token_file="$RESULTS/.comfyrelay-token"
  [ "$(cat "$token_file" 2>/dev/null)" = "$COMFYRELAY_MCP_TOKEN" ] \
    || (umask 077; printf '%s\n' "$COMFYRELAY_MCP_TOKEN" > "$token_file")
  probe="$(python3 "$HARNESS_DIR/servers/probe.py" "$HARNESS_DIR/servers/comfyrelay.json")"
  python3 - "$handoff" "$task" "$HARNESS_DIR/tasks/$task/prompt.md" "$token_file" "$HARNESS_DATA/workspace" "$probe" <<'EOF'
import json, os, sys, time
out, task, prompt, token_file, workspace, probe = sys.argv[1:]
url = f"http://127.0.0.1:{os.environ['COMFYRELAY_PORT']}/mcp"
tools = [f"mcp__comfyrelay__{t}" for t in json.loads(probe)["tools"]]
handoff = {
    "task": task,
    "prompt_file": prompt,
    "prompt": open(prompt).read(),
    "mcp": {"server": "comfyrelay", "transport": "http", "url": url, "token_file": token_file,
            "header": "Authorization: Bearer <the token file's contents>"},
    "workspace": workspace,
    "results_dir": os.path.join(workspace, "results"),
    "allowed_tools": tools,
    "file_tools": "Read and Write, inside the workspace only; no Bash or network",
    "check": f"./external.sh check {task}",
    "started": int(time.time()),
}
with open(out, "w") as f:
    json.dump(handoff, f, indent=2)
print(f"""== {task} is ready for an external agent
prompt:     {prompt}
mcp:        comfyrelay, streamable HTTP at {url}
            header Authorization: Bearer <contents of {token_file}>
workspace:  {workspace}
            the agent's working directory: paths in the prompt are relative to it
tools:      {', '.join(tools)}
            plus Read and Write inside the workspace; nothing else
then:       ./external.sh check {task}
handoff:    {out}""")
EOF
  exit 0
fi

# check
[ -f "$handoff" ] || { echo "no $handoff; run ./external.sh up $task first" >&2; exit 2; }
started="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["started"])' "$handoff")"
elapsed=$(( $(date +%s) - started ))
set +e
detail="$("$HARNESS_DIR/tasks/$task/check.sh" 2>&1 | tail -1)"
rc=$?
set -e
verdict=$([ "$rc" = 0 ] && echo pass || echo fail)
echo "$detail"
# Keep what the agent wrote beside the other runs' files.
mkdir -p "$RESULTS/runs/comfyrelay-$task.files"
cp -r "$HARNESS_DATA/workspace/results/." "$RESULTS/runs/comfyrelay-$task.files/" 2>/dev/null || true
append_score comfyrelay "$task" "$verdict" "$detail" "$elapsed" external ""
exit "$rc"
