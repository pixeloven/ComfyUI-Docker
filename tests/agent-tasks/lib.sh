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
HARNESS_DATA="${HARNESS_DATA:-${TMPDIR:-/tmp}/comfyui-harness}"
COMFY_PORT="${COMFY_PORT:-8188}"
COMFY_URL="${COMFY_URL:-http://127.0.0.1:$COMFY_PORT}"
export COMFY_URL HARNESS_DATA

RESULTS="$HARNESS_DIR/results"
mkdir -p "$RESULTS"

# artokun's HTTP transport needs a bearer token. servers/artokun.json reads it
# as ${ARTOKUN_MCP_TOKEN}, and servers/artokun.sh hands the same value to the
# server. Generated once per checkout, kept in results/ (gitignored).
if [ -z "${ARTOKUN_MCP_TOKEN:-}" ]; then
  [ -s "$RESULTS/.artokun-token" ] || (umask 077; python3 -c 'import secrets; print(secrets.token_hex(24))' > "$RESULTS/.artokun-token")
  ARTOKUN_MCP_TOKEN="$(cat "$RESULTS/.artokun-token")"
fi
export ARTOKUN_MCP_TOKEN

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
