#!/usr/bin/env bash
# Integration test for the comfyrelay image against a booted ComfyUI. It tests
# the sidecar as deployed: the token gate, the arbitrary-UID and read-only
# contract, reaching ComfyUI, and stopping on SIGTERM. No agent runs.
#
#   tests/relay/run.sh [--network MODE] [--out DIR] --comfyui IMAGE <relay-image>
#
#   --comfyui IMAGE   the ComfyUI to boot, a core-cpu image (for example
#                     ghcr.io/pixeloven/comfyui/core:cpu-latest)
#   --network MODE    `host` on a machine without a docker0 bridge. Otherwise
#                     the script creates its own Docker network, and removes it.
#   --out DIR         where results go (default: tests/relay/results, gitignored)
#
# Env: RELAY_COMFY_PORT (default 8188), RELAY_PORT (default 9000),
# RELAY_TIMEOUT in seconds (default 300).
#
# Steps, each fatal:
#   1. The relay refuses to start without a token: exit 2, "Refusing to start".
#   2. Boot ComfyUI (Manager off) and wait for /system_stats.
#   3. Start the relay as UID 12345, GID 0, with a read-only root filesystem
#      and no-new-privileges, pointed at that ComfyUI.
#   4. From inside the relay container, `comfyctl relay probe -o json` passes:
#      401 without the token, initialize, tools/list, server_info, and ComfyUI
#      reachable. The live and pinned ComfyUI versions are reported; a
#      mismatch (a pin bump against an older ComfyUI image) is not a failure.
#   5. `docker stop` ends it within 2 seconds: tini passes SIGTERM on.
#   6. On any failure, print both containers' logs and exit 1.
#
# Every HTTP call runs inside a container, so the host needs only Docker.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"

usage() { sed -n '6,14p' "$0" | sed 's/^# \{0,1\}//'; }

network=""
out="$here/results"
comfyui=""
relay=""
while [ $# -gt 0 ]; do
  case "$1" in
    --network) network="${2:?--network needs a value}"; shift 2 ;;
    --network=*) network="${1#*=}"; shift ;;
    --out) out="${2:?--out needs a value}"; shift 2 ;;
    --comfyui) comfyui="${2:?--comfyui needs a value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    -*) usage >&2; exit 2 ;;
    *) [ -z "$relay" ] || { usage >&2; exit 2; }; relay="$1"; shift ;;
  esac
done
[ -n "$relay" ] && [ -n "$comfyui" ] || { usage >&2; exit 2; }
case "$network" in ""|host) ;; *) echo "--network takes only host" >&2; exit 2 ;; esac

comfy_port="${RELAY_COMFY_PORT:-8188}"
relay_port="${RELAY_PORT:-9000}"
timeout="${RELAY_TIMEOUT:-300}"
token="relay-test-$$-$RANDOM$RANDOM"
comfy="comfyrelay-test-comfyui-$$"
side="comfyrelay-test-relay-$$"
net=""

fail() { echo "RELAY FAIL: $*" >&2; exit 1; }

for img in "$relay" "$comfyui"; do
  docker image inspect "$img" >/dev/null 2>&1 || fail "image $img is not loaded"
done
mkdir -p "$out"
rm -f "$out"/probe.json "$out"/relay.log "$out"/comfyui.log "$out"/summary.json

retire() {
  local c="$1" log="$2" status="${3:-0}"
  docker container inspect "$c" >/dev/null 2>&1 || return 0
  docker logs "$c" > "$log" 2>&1 || true
  if [ "$status" -ne 0 ]; then
    echo "---- container logs ($c) ----" >&2
    cat "$log" >&2
  fi
  docker rm -f "$c" >/dev/null 2>&1 || true
}
cleanup() {
  local status=$?
  retire "$side" "$out/relay.log" "$status"
  retire "$comfy" "$out/comfyui.log" "$status"
  [ -z "$net" ] || docker network rm "$net" >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT

# 1. No token, no server. --network none: it must not need one to decide.
set +e
refusal="$(docker run --rm --network none "$relay" 2>&1)"; rc=$?
set -e
[ "$rc" = 2 ] || fail "without a token the relay exited $rc, not 2: $refusal"
case "$refusal" in *"Refusing to start"*) ;; *) fail "without a token the relay did not say why: $refusal" ;; esac
echo "relay: refuses to start without a token (exit 2)"

# 2. ComfyUI. On the host network both bind loopback, so nothing is exposed on
# the host's interfaces and a ComfyUI already on the port is refused, not used.
comfy_args=(--security-opt no-new-privileges:true -e COMFY_PORT="$comfy_port" -e COMFY_ENABLE_MANAGER=false)
relay_args=()
if [ "$network" = host ]; then
  for p in "$comfy_port" "$relay_port"; do
    if (exec 3<>"/dev/tcp/127.0.0.1/$p") 2>/dev/null; then
      fail "something already listens on 127.0.0.1:$p; stop it or set RELAY_COMFY_PORT / RELAY_PORT"
    fi
  done
  comfy_args+=(--network host -e "CLI_ARGS=--listen 127.0.0.1")
  relay_args+=(--network host -e MCP_HOST=127.0.0.1 -e COMFYUI_URL="http://127.0.0.1:$comfy_port")
else
  net="comfyrelay-test-$$"
  docker network create "$net" >/dev/null
  comfy_args+=(--network "$net" --network-alias comfyui)
  relay_args+=(--network "$net" -e COMFYUI_URL="http://comfyui:$comfy_port")
fi

start="$(date +%s)"
docker run -d --name "$comfy" "${comfy_args[@]}" "$comfyui" >/dev/null
until docker exec "$comfy" curl -fsS --max-time 10 "http://127.0.0.1:$comfy_port/system_stats" >/dev/null 2>&1; do
  [ "$(docker inspect -f '{{.State.Running}}' "$comfy")" = true ] || fail "ComfyUI exited before /system_stats answered"
  [ $(( $(date +%s) - start )) -lt "$timeout" ] || fail "ComfyUI did not answer /system_stats within ${timeout}s"
  sleep 2
done
echo "relay: ComfyUI ($comfyui) answered after $(( $(date +%s) - start ))s"

# 3. The relay, as an arbitrary UID with nothing writable.
docker run -d --name "$side" "${relay_args[@]}" \
  --user 12345:0 --read-only --security-opt no-new-privileges:true \
  -e COMFYUI_MCP_HTTP_TOKEN="$token" -e MCP_PORT="$relay_port" \
  -e COMFYUI_MCP_INSTANCE_ID=relay-test \
  "$relay" >/dev/null
[ "$(docker exec "$side" id -u)" = 12345 ] || fail "the relay is not running as UID 12345"

# 4. The probe, from inside, until the server listens; then once for the record.
probe() {
  docker exec -e COMFYUI_MCP_HTTP_TOKEN="$token" "$side" \
    comfyctl relay probe "http://127.0.0.1:$relay_port/mcp" --timeout 30 "$@"
}
for _ in $(seq 60); do
  [ "$(docker inspect -f '{{.State.Running}}' "$side")" = true ] || fail "the relay exited"
  if text="$(probe 2>&1)"; then break; fi
  case "$text" in *"FAIL  reachable"*) sleep 1 ;; *) break ;; esac
done
echo "$text"
probe -o json > "$out/probe.json" || fail "comfyctl relay probe failed; see $out/probe.json"
live="$(docker exec -i "$comfy" jq -r '.server_info.comfyui.live_version' < "$out/probe.json")"
pinned="$(docker exec -i "$comfy" jq -r '.server_info.comfyui.pinned_version' < "$out/probe.json")"
matches="$(docker exec -i "$comfy" jq -r '.server_info.comfyui.matches_pin' < "$out/probe.json")"
echo "relay: probe passed; ComfyUI live $live, image pinned $pinned, matches: $matches"

# 5. SIGTERM, through tini.
t0="$(date +%s%N)"
docker stop -t 10 "$side" >/dev/null
stop_ms=$(( ($(date +%s%N) - t0) / 1000000 ))
[ "$stop_ms" -lt 2000 ] || fail "docker stop took ${stop_ms}ms; SIGTERM is not reaching the server"
echo "relay: stopped on SIGTERM in ${stop_ms}ms"

cat > "$out/summary.json" <<EOF
{
  "relay_image": "$relay",
  "comfyui_image": "$comfyui",
  "comfyui_live": "$live",
  "comfyui_pinned": "$pinned",
  "matches_pin": $matches,
  "stop_ms": $stop_ms,
  "uid": 12345,
  "read_only": true
}
EOF
echo "relay: PASS, results in $out"
