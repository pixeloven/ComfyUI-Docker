# shellcheck shell=bash
# Shared settings for the harness scripts. Sourced, not executed.

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS_REPO="$(cd "$HARNESS_DIR/../.." && pwd)"

# Local tags. build.sh creates them; HARNESS_IMAGE may point at a published
# image instead (e.g. ghcr.io/pixeloven/comfyui/core:cpu-2.4.2).
HARNESS_RUNTIME_IMAGE="${HARNESS_RUNTIME_IMAGE:-comfyui-harness/runtime:cpu}"
HARNESS_IMAGE="${HARNESS_IMAGE:-comfyui-harness/core:cpu}"
HARNESS_CONTAINER="${HARNESS_CONTAINER:-comfyui-harness}"

# Scratch data volumes. Outside the repo by default, so nothing an agent
# writes can end up in a commit.
# Normalised, so every path built from it (the client's, which stop_mcp_clients
# matches by command line) has one spelling.
HARNESS_DATA="$(realpath -m "${HARNESS_DATA:-${TMPDIR:-/tmp}/comfyui-harness}")"
# The volume directories up.sh creates under it. Each one it creates (rather
# than finds) is listed in HARNESS_CREATED, and down.sh --purge removes only those.
# shellcheck disable=SC2034 # used by up.sh and down.sh
HARNESS_VOLUMES="custom_nodes datasets input models output temp user"
HARNESS_CREATED="$HARNESS_DATA/.harness-created"
created_by_harness() { grep -qxF "$1" "$HARNESS_CREATED" 2>/dev/null || echo "$1" >> "$HARNESS_CREATED"; }
# Empty $HARNESS_DATA/<name> so the next task starts clean, creating it if it is
# missing. Only a directory the harness created is emptied: one it finds but
# didn't make (not in HARNESS_CREATED) is refused, not deleted.
reset_harness_dir() {
  local d="$HARNESS_DATA/$1"
  if [ -e "$d" ] && ! grep -qxF "$1" "$HARNESS_CREATED" 2>/dev/null; then
    echo "not resetting $d: the harness didn't create it. Remove it yourself, or set another HARNESS_DATA" >&2
    return 1
  fi
  rm -rf "${d:?}"
  mkdir -p "$d"
  created_by_harness "$1"
}
# The servers' own HOMEs, where they (and an agent through them) keep config and
# state. external.sh resets both on every `up`; their package caches live
# outside them (npm-cache, uv-cache, uv-python), so a reset keeps the downloads.
# Each is created, and listed in HARNESS_CREATED, here, before anything can
# launch a server into it (claude -p's comfy-mcp included), so a reset or a
# purge always knows it is the harness's. One that already exists unlisted is
# left alone, and a reset refuses it.
SERVER_HOMES="artokun-home comfy-mcp-home"
for _home in $SERVER_HOMES; do
  [ -e "$HARNESS_DATA/$_home" ] || { mkdir -p "$HARNESS_DATA/$_home"; created_by_harness "$_home"; }
done
unset _home
COMFY_PORT="${COMFY_PORT:-8188}"
COMFY_URL="${COMFY_URL:-http://127.0.0.1:$COMFY_PORT}"
COMFYRELAY_PORT="${COMFYRELAY_PORT:-9200}"
export COMFY_URL HARNESS_DATA COMFYRELAY_PORT

# Markers, tokens, the scorecard and transcripts. Two runs at once on one host
# each need their own HARNESS_RESULTS, as well as their own HARNESS_CONTAINER,
# COMFY_PORT, COMFYRELAY_PORT and HARNESS_DATA.
RESULTS="${HARNESS_RESULTS:-$HARNESS_DIR/results}"
mkdir -p "$RESULTS"
RESULTS="$(cd "$RESULTS" && pwd)"
HARNESS_RESULTS="$RESULTS"
export HARNESS_RESULTS

# artokun's HTTP transport needs a bearer token. servers/artokun.json reads it
# as ${ARTOKUN_MCP_TOKEN}, and servers/artokun.sh hands the same value to the
# server. Generated once per checkout, kept in results/ (gitignored).
if [ -z "${ARTOKUN_MCP_TOKEN:-}" ]; then
  [ -s "$RESULTS/.artokun-token" ] || (umask 077; python3 -c 'import secrets; print(secrets.token_hex(24))' > "$RESULTS/.artokun-token")
  ARTOKUN_MCP_TOKEN="$(cat "$RESULTS/.artokun-token")"
fi
export ARTOKUN_MCP_TOKEN
# The copy an external agent reads it from (external.sh writes it): beside the
# scratch data, like comfyrelay's below, not in results/ with the answers.
# shellcheck disable=SC2034 # used by external.sh and down.sh
ARTOKUN_TOKEN_FILE="$HARNESS_DATA/.artokun-token"

# comfyrelay's token: servers/comfyrelay.json reads it as ${COMFYRELAY_MCP_TOKEN},
# and servers/comfyrelay.sh starts the server with it. An external agent reads
# it from this file, so it is kept beside the scratch data, outside the repo,
# results/ and the agent's workspace: nowhere near the answers.
COMFYRELAY_TOKEN_FILE="$HARNESS_DATA/.comfyrelay-token"
if [ -z "${COMFYRELAY_MCP_TOKEN:-}" ]; then
  mkdir -p "$HARNESS_DATA"
  [ -s "$COMFYRELAY_TOKEN_FILE" ] || (umask 077; python3 -c 'import secrets; print(secrets.token_hex(24))' > "$COMFYRELAY_TOKEN_FILE")
  COMFYRELAY_MCP_TOKEN="$(cat "$COMFYRELAY_TOKEN_FILE")"
fi
export COMFYRELAY_MCP_TOKEN

# Every external agent reaches its server through this read-only copy of
# servers/mcp_client.py, which external.sh installs beside the server's spec
# (MCP_SPEC). The copy's path is unique to HARNESS_DATA, so stop_mcp_clients
# stops only the connections this run's agents opened, and any server one
# launched: each runs in its client's process group.
MCP_CLIENT="$HARNESS_DATA/bin/mcp_client.py"
# shellcheck disable=SC2034 # used by external.sh and down.sh
MCP_SPEC="$HARNESS_DATA/bin/server.json"
stop_mcp_clients() {
  local pid
  for pid in $(pgrep -f "$MCP_CLIENT _serve" || true); do
    kill -TERM -- "-$pid" 2>/dev/null || true
  done
}

# The environment a server the harness launches gets: PATH, TMPDIR and the
# locale, as NAME=VALUE lines, and nothing else from the operator's shell,
# which can hold credentials. Each launcher adds the variables it needs.
base_env() {
  local v
  for v in PATH TMPDIR LANG LANGUAGE $(compgen -e | grep '^LC_' || true); do
    [ -n "${!v+x}" ] && printf '%s=%s\n' "$v" "${!v}"
  done
}

# The ComfyUI pin, read from docker-bake.hcl (the single source of truth).
bake_pin() {
  sed -n '/^variable "COMFYUI_VERSION"/,/^}/s/^ *default *= *"\(.*\)"/\1/p' "$HARNESS_REPO/docker-bake.hcl"
}

# Wait until /system_stats answers, or give up after $1 seconds (default 180).
wait_ready() {
  local deadline=$(( $(date +%s) + ${1:-180} ))
  until curl -fsS "$COMFY_URL/system_stats" >/dev/null 2>&1; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
      echo "ComfyUI did not answer $COMFY_URL/system_stats in time" >&2
      docker logs --tail 50 "$HARNESS_CONTAINER" >&2 || true
      return 1
    fi
    sleep 2
  done
}

# The stdlib-only Python helper that the setup and check scripts share.
hpy() { python3 "$HARNESS_DIR/harness.py" "$@"; }

# Reset a task. Run it before the server starts: T2's reset restarts ComfyUI,
# and the server should meet the instance the agent will use. The workspace is
# emptied too, so an agent never sees files an earlier run left behind; setup
# then places this task's inputs.
#
# ComfyUI's queue is emptied first: pending prompts cleared, the running one
# interrupted, and then a wait until nothing runs or waits. Otherwise a prompt an
# earlier run left queued would finish after setup's mark and count as this
# task's work, with a genuinely new file. Then ComfyUI is asked to drop its
# execution cache (POST /free with free_memory resets it, and unloads models),
# so a graph an earlier task ran is executed again rather than served from the
# cache. Its volumes and /history do carry over: every check counts only what
# is new since its setup.
prepare_task() {
  created_by_harness workspace
  rm -rf "$HARNESS_DATA/workspace"
  mkdir -p "$HARNESS_DATA/workspace/results" "$RESULTS/runs"
  curl -fsS -o /dev/null -X POST -H 'Content-Type: application/json' -d '{"clear": true}' "$COMFY_URL/queue"
  curl -fsS -o /dev/null -X POST -H 'Content-Type: application/json' -d '{}' "$COMFY_URL/interrupt"
  local deadline=$(( $(date +%s) + ${HARNESS_QUEUE_TIMEOUT:-120} ))
  until curl -fsS "$COMFY_URL/queue" \
      | python3 -c 'import json,sys; q=json.load(sys.stdin); sys.exit(bool(q["queue_running"] or q["queue_pending"]))'; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
      echo "ComfyUI's queue at $COMFY_URL did not empty within ${HARNESS_QUEUE_TIMEOUT:-120}s; not setting up $1" >&2
      return 1
    fi
    curl -fsS -o /dev/null -X POST -H 'Content-Type: application/json' -d '{}' "$COMFY_URL/interrupt"
    sleep 1
  done
  curl -fsS -o /dev/null -X POST -H 'Content-Type: application/json' \
    -d '{"unload_models": true, "free_memory": true}' "$COMFY_URL/free"
  "$HARNESS_DIR/tasks/$1/setup.sh"
}

# Append a row to results/scorecard.csv:
#   append_score <server> <task> <pass|fail> <detail> <seconds> <mode> <transcript or "">
# cost_usd_notional is what claude reports; on a subscription it is plan quota,
# not a charge.
append_score() {
  local sc="$RESULTS/scorecard.csv"
  [ -s "$sc" ] || echo "timestamp,server,task,result,detail,seconds,mode,turns,cost_usd_notional" > "$sc"
  python3 - "$sc" "$@" <<'EOF'
import csv, json, sys
from datetime import datetime, timezone
path, *row, transcript = sys.argv[1:]
turns = cost = ""
if transcript:
    try:
        for line in open(transcript):
            if line.startswith("{") and '"type":"result"' in line.replace(" ", ""):
                r = json.loads(line)
                turns, cost = r.get("num_turns", ""), r.get("total_cost_usd", "")
    except (OSError, ValueError):
        pass
with open(path, "a", newline="") as f:
    csv.writer(f).writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), *row, turns, cost])
EOF
}
