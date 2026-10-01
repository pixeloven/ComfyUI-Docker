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
# comfyrelay:latest, the image under test, built locally). Both containers use
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
    # Reuse it only if it is the instance this run describes.
    image="$(docker inspect -f '{{.Config.Image}}' "$HARNESS_CONTAINER")"
    data="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/app/user"}}{{.Source}}{{end}}{{end}}' "$HARNESS_CONTAINER")"
    want_data="$(realpath -m "$HARNESS_DATA/user")"
    if [ "$image" != "$HARNESS_IMAGE" ] || [ "$(realpath -m "$data")" != "$want_data" ]; then
      echo "$HARNESS_CONTAINER is running $image with $data; this run wants $HARNESS_IMAGE with $want_data." >&2
      echo "Run ./external.sh down first, or set HARNESS_CONTAINER for a separate run." >&2
      exit 1
    fi
  else
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
  hpy handoff "$task" "$token_file" "$(python3 "$HARNESS_DIR/servers/probe.py" "$HARNESS_DIR/servers/comfyrelay.json")"
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
