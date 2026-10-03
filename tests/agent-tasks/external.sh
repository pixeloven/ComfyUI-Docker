#!/usr/bin/env bash
# Run a task against one MCP server with an agent the harness doesn't launch: a
# subagent of the lead session. Three commands, so the lead can dispatch the
# agent between them:
#
#   ./external.sh up <task> [--server comfyrelay|artokun|comfy-mcp]
#                                 boot core-cpu if it isn't running (up.sh, then
#                                 groundtruth.sh), reset the task (its setup.sh),
#                                 stop every other server, start this one (default
#                                 comfyrelay), and print the brief to give the agent:
#                                 the same preamble for every server (the rules, and the
#                                 harness's MCP client to use), then the task's prompt.
#                                 Also written to <workspace>/TASK.md and
#                                 results/<server>-<task>.handoff.json
#   (the agent does the task, and writes its results under the workspace)
#   ./external.sh check <task> [--server ...]
#                                 run the task's check.sh, append a scorecard row with
#                                 the server and mode "external (not sandboxed)",
#                                 exit 0 on PASS. It refuses (exit 2) a server the
#                                 workspace wasn't set up for. Run it before the next
#                                 `up`, which empties the workspace.
#   ./external.sh down [--purge]  stop ComfyUI and every server (down.sh)
#
# Tasks: T1, T3, T4, T5 and T6-neutral on every server; T2-refuse and the full
# T6 (with citations) on comfyrelay, T2 on the others. `up` can be repeated for
# the next task on the same instance. Each one restarts the server, empties the
# workspace and both servers' HOMEs, removes a T2 pack, and drops ComfyUI's
# execution cache; ComfyUI's volumes and /history carry over, and every check
# counts only what is new since its setup. Every agent uses the same client, a
# read-only copy of servers/mcp_client.py, whatever the server's transport.
#
# Nothing confines the agent: it is told to use only the server. The confined,
# blind run is `claude -p` (HARNESS_RUN=1 ./run.sh).
#
# The images: HARNESS_IMAGE (core-cpu, default the local build from build.sh;
# e.g. ghcr.io/pixeloven/comfyui/core:cpu-latest) and COMFYRELAY_IMAGE (default
# ghcr.io/pixeloven/comfyui/mcp:local, built locally). T5's, T6's and
# T6-neutral's checks use the relay image whatever the server. The containers use --network host
# and bind loopback. For several runs on one host, give each its own
# HARNESS_CONTAINER (the prefix of the container names), COMFY_PORT,
# COMFYRELAY_PORT, ARTOKUN_PORT, HARNESS_DATA and HARNESS_RESULTS.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

usage() { sed -n '2,41p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }

cmd="${1:-}"
case "$cmd" in
  up|check)
    shift
    task="" server=comfyrelay
    while [ $# -gt 0 ]; do
      case "$1" in
        --server) [ $# -ge 2 ] || usage; server="$2"; shift 2 ;;
        --server=*) server="${1#--server=}"; shift ;;
        -*) usage ;;
        *) [ -z "$task" ] || usage; task="$1"; shift ;;
      esac
    done
    [ -n "$task" ] || usage
    [ -f "$HARNESS_DIR/tasks/$task/prompt.md" ] || { echo "no task $task" >&2; exit 2; }
    handoff="$RESULTS/$server-$task.handoff.json"
    ;;
  down) shift; exec "$HARNESS_DIR/down.sh" "$@" ;;
  *) usage ;;
esac

if [ "$cmd" = up ]; then
  # comfyrelay must refuse the install, so it gets the inverted T2; the others
  # get T2. The full T6 cites pages of comfyrelay's own docs index, so only it
  # runs that; T6-neutral is the version every server runs.
  case "$server:$task" in
    comfyrelay:T2) echo "comfyrelay runs T2-refuse, not T2" >&2; exit 2 ;;
    artokun:T2-refuse|comfy-mcp:T2-refuse) echo "$server runs T2, not T2-refuse" >&2; exit 2 ;;
    artokun:T6|comfy-mcp:T6) echo "$server runs T6-neutral, not T6" >&2; exit 2 ;;
    comfyrelay:*|artokun:*|comfy-mcp:*) ;;
    *) echo "unknown server $server; use comfyrelay, artokun or comfy-mcp" >&2; exit 2 ;;
  esac
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
  # This task's earlier handoffs go, whatever server they were for, so `check`
  # can't score this run's workspace as another server's.
  for s in comfyrelay artokun comfy-mcp; do rm -f "$RESULTS/$s-$task.handoff.json"; done
  # Only the server under test runs while the agent works, including any
  # server an earlier agent's client launched.
  for s in "$HARNESS_DIR"/servers/*.sh; do "$s" down >/dev/null 2>&1 || true; done
  stop_mcp_clients
  # What an earlier task left behind goes: the servers' HOMEs (what a server,
  # or an agent through it, wrote there), and T2's pack, which an install
  # leaves on the volume (T2's own setups remove it anyway). prepare_task then
  # empties the workspace and drops ComfyUI's execution cache. ComfyUI's
  # volumes and /history still carry over; checks count only what's new.
  for d in $SERVER_HOMES; do reset_harness_dir "$d"; done
  case "$task" in T2|T2-refuse) ;; *) "$HARNESS_DIR/tasks/T2/reset.sh" --if-installed >/dev/null ;; esac
  export HARNESS_EXTERNAL=1   # setups that would fall back to committed answers fail instead
  prepare_task "$task"
  # check refuses a --server that isn't the one this workspace was set up for.
  printf '%s\n' "$server" > "$HARNESS_DATA/workspace/.harness-server"

  # Every agent reaches its server through the same client, a read-only copy
  # outside the workspace and the repo, beside the spec that tells it how.
  [ -d "$HARNESS_DATA/bin" ] || { mkdir -p "$HARNESS_DATA/bin"; created_by_harness bin; }
  rm -f "$MCP_CLIENT"
  install -m 0444 "$HARNESS_DIR/servers/mcp_client.py" "$MCP_CLIENT"
  token_file=""
  case "$server" in
    comfyrelay)
      "$HARNESS_DIR/servers/comfyrelay.sh" up
      token_file="$COMFYRELAY_TOKEN_FILE" token="$COMFYRELAY_MCP_TOKEN"
      ;;
    artokun)
      "$HARNESS_DIR/servers/artokun.sh" up
      token_file="$ARTOKUN_TOKEN_FILE" token="$ARTOKUN_MCP_TOKEN"
      ;;
  esac
  # The token may come from the environment; the client reads it from a file,
  # kept beside the scratch data: outside the repo, results/ and the workspace.
  if [ -n "$token_file" ]; then
    [ "$(cat "$token_file" 2>/dev/null)" = "$token" ] \
      || (umask 077; printf '%s\n' "$token" > "$token_file")
    chmod 600 "$token_file"
  fi
  # The tool list, for the handoff. For comfy-mcp this also fills uv's cache,
  # so the client's launch (UV_OFFLINE=1) needs no package index.
  tools="$(python3 "$HARNESS_DIR/servers/probe.py" "$HARNESS_DIR/servers/$server.json")"
  hpy handoff "$task" "$server" "$token_file" "$MCP_CLIENT" "$MCP_SPEC" "$tools"
  exit 0
fi

# check
[ -f "$handoff" ] || { echo "no $handoff; run ./external.sh up $task --server $server first" >&2; exit 2; }
set_up_for="$(cat "$HARNESS_DATA/workspace/.harness-server" 2>/dev/null || true)"
[ "$set_up_for" = "$server" ] || {
  echo "the workspace was set up for ${set_up_for:-no server}, not $server; run ./external.sh up $task --server $server first" >&2
  exit 2
}
started="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["started"])' "$handoff")"
elapsed=$(( $(date +%s) - started ))
# T5's check ends with a self-test of comfyrelay's runnability verdicts,
# reported separately and scored for comfyrelay only. For another server, the
# relay runs for that self-test only, after the agent has finished; if it
# can't start, the self-test says so and the task's own result stands.
if [ "$task" = T5 ] && [ "$server" != comfyrelay ]; then
  "$HARNESS_DIR/servers/comfyrelay.sh" up || echo "comfyrelay did not start for T5's self-test" >&2
  trap '"$HARNESS_DIR/servers/comfyrelay.sh" down' EXIT
fi
export HARNESS_SERVER="$server"
set +e
detail="$("$HARNESS_DIR/tasks/$task/check.sh" 2>&1 | tail -1)"
rc=$?
set -e
verdict=$([ "$rc" = 0 ] && echo pass || echo fail)
echo "$detail"
# Keep what the agent wrote beside the other runs' files.
mkdir -p "$RESULTS/runs/$server-$task.files"
cp -r "$HARNESS_DATA/workspace/results/." "$RESULTS/runs/$server-$task.files/" 2>/dev/null || true
append_score "$server" "$task" "$verdict" "$detail" "$elapsed" "external (not sandboxed)" ""
exit "$rc"
