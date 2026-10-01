#!/usr/bin/env bash
# run.sh <server> <task>   e.g.  run.sh comfy-mcp T1
# run.sh <server> probe [<tool> '<json args>']
#                          start the server, send `initialize` + `tools/list`
#                          (and optionally call one tool), stop. No agent.
#
# 1. starts the server if it has a launcher (servers/<server>.sh),
# 2. resets the task (tasks/<task>/setup.sh),
# 3. prints the exact `claude -p` command, and runs it only when HARNESS_RUN=1
#    (an agent session; it needs the owner's approval),
# 4. runs tasks/<task>/check.sh and appends a row to results/scorecard.csv.
#
# Knobs: HARNESS_RUN=1, HARNESS_TIMEOUT (seconds, default 900),
# HARNESS_BUDGET_USD (default 5; a runaway guard, not a price),
# HARNESS_MODEL (default claude-opus-5-5, pinned so every run is comparable),
# HARNESS_BARE=1 (adds --bare: no CLAUDE.md or user memory; needs ANTHROPIC_API_KEY).
set -euo pipefail
. "$(dirname "$0")/lib.sh"

server="${1:?usage: run.sh <server> <task|probe>}"
task="${2:?usage: run.sh <server> <task|probe>}"
cfg="$HARNESS_DIR/servers/$server.json"
hook="$HARNESS_DIR/servers/$server.sh"
[ -f "$cfg" ] || { echo "no server config $cfg" >&2; exit 2; }
key="$(python3 -c 'import json,sys; print(next(iter(json.load(open(sys.argv[1]))["mcpServers"])))' "$cfg")"

curl -fsS -o /dev/null "$COMFY_URL/system_stats" || { echo "ComfyUI is not up at $COMFY_URL; run ./up.sh" >&2; exit 1; }

start_server() {
  if [ -x "$hook" ]; then
    "$hook" up
    trap '"$hook" down' EXIT
  fi
}

if [ "$task" = probe ]; then
  start_server
  python3 "$HARNESS_DIR/servers/probe.py" "$cfg" "${@:3}"
  exit
fi

prompt="$HARNESS_DIR/tasks/$task/prompt.md"
[ -f "$prompt" ] || { echo "no task $task" >&2; exit 2; }

workspace="$HARNESS_DATA/workspace"
prepare_task "$task"
start_server

# Read and Write only: no Bash, so the agent cannot curl ComfyUI around the
# MCP server. --restricted also confines those file tools to the workspace,
# which holds nothing but the task's own inputs, and ignores user, project and
# local settings.
# stream-json (which needs --verbose) records every tool call, so the
# transcript shows what the agent did, not just its final answer.
flags=(
  --mcp-config "$cfg" --strict-mcp-config
  --output-format stream-json --verbose
  --restricted --tools "Read,Write"
  --allowedTools "Read,Write,mcp__$key"
  --permission-mode dontAsk
  --max-budget-usd "${HARNESS_BUDGET_USD:-5}"
  --no-session-persistence
  --model "${HARNESS_MODEL:-claude-opus-5-5}"
)
[ "${HARNESS_BARE:-0}" = 1 ] && flags+=(--bare)
timeout_s="${HARNESS_TIMEOUT:-900}"

echo "# the agent command, run in $workspace:"
# shellcheck disable=SC2016 # the $(cat ...) is printed for the reader, not run
printf 'timeout %s claude -p "$(cat %q)" ' "$timeout_s" "$prompt"
printf '%q ' "${flags[@]}"
echo

start=$(date +%s)
mode=dry-run
if [ "${HARNESS_RUN:-0}" = 1 ]; then
  mode=agent
  transcript="$RESULTS/runs/$server-$task.jsonl"
  (cd "$workspace" && timeout "$timeout_s" claude -p "$(cat "$prompt")" "${flags[@]}" < /dev/null) > "$transcript" \
    || echo "claude exited $? (see $transcript)" >&2
  # Keep what the agent wrote beside its transcript.
  cp -r "$workspace/results/." "$RESULTS/runs/$server-$task.files/" 2>/dev/null || true
else
  echo "HARNESS_RUN is not 1: not launching the agent. The check below scores whatever state is there."
fi
elapsed=$(( $(date +%s) - start ))

set +e
detail="$("$HARNESS_DIR/tasks/$task/check.sh" 2>&1 | tail -1)"
rc=$?
set -e
verdict=$([ "$rc" = 0 ] && echo pass || echo fail)
echo "$detail"
append_score "$server" "$task" "$verdict" "$detail" "$elapsed" "$mode" "${transcript:-}"
