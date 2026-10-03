#!/usr/bin/env bash
# Run a task against comfyrelay with an agent the harness doesn't launch: a
# subagent of the lead session. Three commands, so the lead can dispatch the
# agent between them:
#
#   ./external.sh up <task>       boot core-cpu if it isn't running (up.sh, then
#                                 groundtruth.sh), reset the task (its setup.sh),
#                                 start comfyrelay, and print the brief to give the
#                                 agent: a preamble (endpoint, token file, MCP steps,
#                                 rules), then the task's prompt. Also written to
#                                 <workspace>/TASK.md and results/<task>.handoff.json
#   (the agent does the task, and writes its results under the workspace)
#   ./external.sh check <task>    run the task's check.sh, append a scorecard row with
#                                 mode "external (not sandboxed)", exit 0 on PASS
#   ./external.sh down [--purge]  stop ComfyUI and the relay (down.sh)
#
# Tasks: T1, T2-refuse, T3, T4, T5, T6. `up` can be repeated for the next task
# on the same instance; each one restarts the relay.
#
# Nothing confines the agent: it is told to use only the relay. The confined,
# blind run is `claude -p` (HARNESS_RUN=1 ./run.sh).
#
# The images: HARNESS_IMAGE (core-cpu, default the local build from build.sh;
# e.g. ghcr.io/pixeloven/comfyui/core:cpu-latest) and COMFYRELAY_IMAGE (default
# ghcr.io/pixeloven/comfyui/mcp:local, the image under test, built locally). Both containers use
# --network host and bind loopback. For several runs on one host, give each its
# own HARNESS_CONTAINER (the prefix of both container names), COMFY_PORT,
# COMFYRELAY_PORT, HARNESS_DATA and HARNESS_RESULTS.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

usage() { sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }

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
  if [ "$(docker inspect -f '{{.State.Running}}' "$HARNESS_CONTAINER" 2>/dev/null)" = true ]; then
    # Reuse it only if it is the instance this run describes: the same image
    # (by ID, so a re-pointed tag doesn't match and a digest reference does),
    # the same data directory, and the same port.
    image="$(docker inspect -f '{{.Image}}' "$HARNESS_CONTAINER")"
    want_image="$(docker image inspect -f '{{.Id}}' "$HARNESS_IMAGE" 2>/dev/null || echo "missing")"
    data="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/app/user"}}{{.Source}}{{end}}{{end}}' "$HARNESS_CONTAINER")"
    want_data="$(realpath -m "$HARNESS_DATA/user")"
    port="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$HARNESS_CONTAINER" | sed -n 's/^COMFY_PORT=//p')"
    if [ "$image" != "$want_image" ] || [ "$(realpath -m "$data")" != "$want_data" ] || [ "$port" != "$COMFY_PORT" ]; then
      echo "$HARNESS_CONTAINER runs image $image on $data, port $port;" >&2
      echo "this run wants $HARNESS_IMAGE ($want_image) on $want_data, port $COMFY_PORT." >&2
      echo "Run ./external.sh down first, or set HARNESS_CONTAINER for a separate run." >&2
      exit 1
    fi
  else
    "$HARNESS_DIR/up.sh" >/dev/null
  fi
  # A fresh HARNESS_RESULTS on a reused instance has no dump yet; T3 needs one.
  [ -f "$RESULTS/object_info.json" ] || "$HARNESS_DIR/groundtruth.sh" >/dev/null
  rm -f "$handoff"
  export HARNESS_EXTERNAL=1   # setups that would fall back to committed answers fail instead
  prepare_task "$task"
  "$HARNESS_DIR/servers/comfyrelay.sh" up

  # The token may come from the environment; the agent reads it from a file.
  [ "$(cat "$COMFYRELAY_TOKEN_FILE" 2>/dev/null)" = "$COMFYRELAY_MCP_TOKEN" ] \
    || (umask 077; printf '%s\n' "$COMFYRELAY_MCP_TOKEN" > "$COMFYRELAY_TOKEN_FILE")
  chmod 600 "$COMFYRELAY_TOKEN_FILE"
  hpy handoff "$task" "$COMFYRELAY_TOKEN_FILE" "$(python3 "$HARNESS_DIR/servers/probe.py" "$HARNESS_DIR/servers/comfyrelay.json")"
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
append_score comfyrelay "$task" "$verdict" "$detail" "$elapsed" "external (not sandboxed)" ""
exit "$rc"
