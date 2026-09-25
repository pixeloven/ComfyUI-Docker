#!/usr/bin/env bash
# run.sh <server> <task>   e.g.  run.sh comfy-mcp T1
# run.sh <server> probe [<tool> '<json args>']
#                          start the server, send `initialize` + `tools/list`
#                          (and optionally call one tool), stop. No agent.
#
# 1. starts the server if it has a launcher (servers/<server>.sh),
# 2. resets the task (tasks/<task>/setup.sh),
# 3. prints the exact `claude -p` command, and runs it only when HARNESS_RUN=1
#    (a billed agent session; it needs the owner's approval),
# 4. runs tasks/<task>/check.sh and appends a row to results/scorecard.csv.
#
# Knobs: HARNESS_RUN=1, HARNESS_TIMEOUT (seconds, default 900),
# HARNESS_BUDGET_USD (default 5), HARNESS_MODEL (default: claude's default),
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

# Reset first: T2's reset restarts ComfyUI, and the server should meet the
# instance the agent will use.
"$HARNESS_DIR/tasks/$task/setup.sh"
start_server
workspace="$HARNESS_DATA/workspace"
mkdir -p "$workspace/results" "$RESULTS/runs"

# Read and Write only: no Bash, so the agent cannot curl ComfyUI around the
# MCP server. --restricted also confines those file tools to the workspace,
# which holds nothing but the task's own inputs, and ignores user, project and
# local settings.
flags=(
  --mcp-config "$cfg" --strict-mcp-config
  --output-format json
  --restricted --tools "Read,Write"
  --allowedTools "Read,Write,mcp__$key"
  --permission-mode dontAsk
  --max-budget-usd "${HARNESS_BUDGET_USD:-5}"
  --no-session-persistence
)
[ -n "${HARNESS_MODEL:-}" ] && flags+=(--model "$HARNESS_MODEL")
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
  transcript="$RESULTS/runs/$server-$task.json"
  (cd "$workspace" && timeout "$timeout_s" claude -p "$(cat "$prompt")" "${flags[@]}") > "$transcript" \
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

sc="$RESULTS/scorecard.csv"
[ -s "$sc" ] || echo "timestamp,server,task,result,detail,seconds,mode,turns,cost_usd" > "$sc"
python3 - "$sc" "$server" "$task" "$verdict" "$detail" "$elapsed" "$mode" "${transcript:-}" <<'EOF'
import csv, json, sys
from datetime import datetime, timezone
path, *row, transcript = sys.argv[1:]
turns = cost = ""
if transcript:
    try:
        r = json.load(open(transcript))
        turns, cost = r.get("num_turns", ""), r.get("total_cost_usd", "")
    except (OSError, ValueError):
        pass
with open(path, "a", newline="") as f:
    csv.writer(f).writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), *row, turns, cost])
EOF
