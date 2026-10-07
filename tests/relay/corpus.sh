#!/usr/bin/env bash
# D8's test bar for the mcp-convert image (#167): every open template the
# ComfyUI serves, converted through the relay, validated by the relay and by
# ComfyUI, and identical to the frontend's own export in a plain browser tab.
# The checks are services/comfyrelay/tests/test_relay_convert_corpus.py; this
# boots what it runs against.
#
#   tests/relay/corpus.sh [--out DIR] --comfyui IMAGE <mcp-convert image>
#
#   --comfyui IMAGE   the ComfyUI to boot, a core-cpu image at the pin
#   --out DIR         where results go (default: tests/relay/results/corpus)
#
# Env: CORPUS_COMFY_PORT (default 8188), CORPUS_RELAY_PORT (default 9000),
# CORPUS_NAME, the container name prefix (default comfyrelay-corpus),
# CORPUS_PAGES, the relay's tabs (default 4), CORPUS_TABS, the oracle's
# (default 4), RELAY_TIMEOUT in seconds (default 300). The scratch folders go
# under TMPDIR.
#
# Both containers run on the host network, bound to loopback; the test runs on
# the host, so it needs uv and the `convert` extra's Chromium
# (`uv run --locked --extra convert playwright install --only-shell chromium`).
#
#   1. Boot ComfyUI (Manager off) as this user, with empty model and input
#      folders bind-mounted for the test's placeholders, and
#      tests/relay/validate_only.py as a custom node, so /prompt validates a
#      marked graph without queueing it. Check that the custom node loaded.
#   2. Start the relay as UID 12345, read-only with a tmpfs /tmp, with
#      CORPUS_PAGES tabs and as many large requests at once (a UI template can
#      be over 1 MiB), and wait for `comfyctl relay probe`.
#   3. Run the test. It fails unless every open template passes; a skipped
#      test fails too.
#   4. ComfyUI's queue and history are still empty: nothing ran.
#   5. On any failure, print both containers' logs and exit 1.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"

usage() { sed -n '7,17p' "$0" | sed 's/^# \{0,1\}//'; }

out="$here/results/corpus"
comfyui=""
relay=""
while [ $# -gt 0 ]; do
  case "$1" in
    --out) out="${2:?--out needs a value}"; shift 2 ;;
    --comfyui) comfyui="${2:?--comfyui needs a value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    -*) usage >&2; exit 2 ;;
    *) [ -z "$relay" ] || { usage >&2; exit 2; }; relay="$1"; shift ;;
  esac
done
[ -n "$relay" ] && [ -n "$comfyui" ] || { usage >&2; exit 2; }

comfy_port="${CORPUS_COMFY_PORT:-8188}"
relay_port="${CORPUS_RELAY_PORT:-9000}"
name="${CORPUS_NAME:-comfyrelay-corpus}"
pages="${CORPUS_PAGES:-4}"
tabs="${CORPUS_TABS:-4}"
timeout="${RELAY_TIMEOUT:-300}"
# The server refuses a token under 32 characters.
token="corpus-$(od -An -tx1 -N16 /dev/urandom | tr -d ' \n')"
comfy="$name-comfyui"
side="$name-relay"
url="http://127.0.0.1:$comfy_port"

fail() { echo "CORPUS FAIL: $*" >&2; exit 1; }

for img in "$relay" "$comfyui"; do
  docker image inspect "$img" >/dev/null 2>&1 || fail "image $img is not loaded"
done
case "$(docker image inspect -f '{{json .Config.Env}}' "$relay")" in
  *'"COMFYUI_MCP_CONVERT=1"'*) ;;
  *) fail "$relay does not convert (no COMFYUI_MCP_CONVERT=1): the corpus needs mcp-convert" ;;
esac
for p in "$comfy_port" "$relay_port"; do
  if (exec 3<>"/dev/tcp/127.0.0.1/$p") 2>/dev/null; then
    fail "something already listens on 127.0.0.1:$p; stop it or set CORPUS_COMFY_PORT / CORPUS_RELAY_PORT"
  fi
done
mkdir -p "$out"
rm -f "$out"/corpus.json "$out"/pytest.log "$out"/relay.log "$out"/comfyui.log
work="$(mktemp -d "${TMPDIR:-/tmp}/comfyrelay-corpus.XXXXXX")"
mkdir -p "$work/models" "$work/input"

retire() {
  local c="$1" log="$2" status="${3:-0}"
  docker container inspect "$c" >/dev/null 2>&1 || return 0
  docker logs "$c" > "$log" 2>&1 || true
  if [ "$status" -ne 0 ]; then
    echo "---- container logs ($c), last 200 lines ----" >&2
    tail -n 200 "$log" >&2
  fi
  docker rm -f "$c" >/dev/null 2>&1 || true
}
cleanup() {
  local status=$?
  retire "$side" "$out/relay.log" "$status"
  retire "$comfy" "$out/comfyui.log" "$status"
  rm -rf "$work"
  exit "$status"
}
trap cleanup EXIT

# 1. ComfyUI, as this user, so the test can write its placeholders into the
# mounted folders and remove them after.
start="$(date +%s)"
docker run -d --name "$comfy" --network host --security-opt no-new-privileges:true \
  -e COMFY_PORT="$comfy_port" -e COMFY_ENABLE_MANAGER=false -e "CLI_ARGS=--listen 127.0.0.1" \
  -e PUID="$(id -u)" -e PGID="$(id -g)" \
  -v "$work/models:/app/models" -v "$work/input:/app/input" \
  -v "$here/validate_only.py:/app/custom_nodes/comfyrelay_validate_only.py:ro" \
  "$comfyui" >/dev/null
until curl -fsS --max-time 10 "$url/system_stats" >/dev/null 2>&1; do
  [ "$(docker inspect -f '{{.State.Running}}' "$comfy")" = true ] || fail "ComfyUI exited before /system_stats answered"
  [ $(( $(date +%s) - start )) -lt "$timeout" ] || fail "ComfyUI did not answer /system_stats within ${timeout}s"
  sleep 2
done
echo "corpus: ComfyUI ($comfyui) answered after $(( $(date +%s) - start ))s"
docker logs "$comfy" 2>&1 | grep -q 'comfyrelay_validate_only: installed' \
  || fail "ComfyUI did not load tests/relay/validate_only.py, so /prompt would queue what it validates"

# 2. The relay.
docker run -d --name "$side" --network host \
  --user 12345:0 --read-only --tmpfs /tmp --security-opt no-new-privileges:true \
  -e MCP_HOST=127.0.0.1 -e MCP_PORT="$relay_port" -e COMFYUI_URL="$url" \
  -e COMFYUI_MCP_HTTP_TOKEN="$token" -e COMFYUI_MCP_CONVERT_PAGES="$pages" \
  -e COMFYUI_MCP_MAX_LARGE_REQUESTS="$pages" -e COMFYUI_MCP_INSTANCE_ID=corpus \
  "$relay" >/dev/null
probe() {
  docker exec -e COMFYUI_MCP_HTTP_TOKEN="$token" "$side" \
    comfyctl relay probe "http://127.0.0.1:$relay_port/mcp" --timeout 30
}
for _ in $(seq 60); do
  [ "$(docker inspect -f '{{.State.Running}}' "$side")" = true ] || fail "the relay exited"
  if text="$(probe 2>&1)"; then break; fi
  case "$text" in *"FAIL  reachable"*) sleep 1 ;; *) fail "comfyctl relay probe failed: $text" ;; esac
done
probe >/dev/null 2>&1 || fail "the relay did not pass comfyctl relay probe"
echo "corpus: the relay ($relay) passed its probe"

# 3. The corpus.
t0="$(date +%s)"
set +e
(
  cd "$repo/services"
  COMFYRELAY_LIVE_COMFYUI_URL="$url" \
  COMFYRELAY_CORPUS_RELAY_URL="http://127.0.0.1:$relay_port/mcp" \
  COMFYRELAY_CORPUS_TOKEN="$token" \
  COMFYRELAY_CORPUS_MODELS="$work/models" COMFYRELAY_CORPUS_INPUT="$work/input" \
  COMFYRELAY_CORPUS_OUT="$out" COMFYRELAY_CORPUS_CALLS="$pages" COMFYRELAY_CORPUS_TABS="$tabs" \
    uv run --locked --extra convert pytest -v -rs -s comfyrelay/tests/test_relay_convert_corpus.py
) 2>&1 | tee "$out/pytest.log"
rc="${PIPESTATUS[0]}"
set -e
echo "corpus: the test took $(( $(date +%s) - t0 ))s"
[ "$rc" = 0 ] || fail "the corpus test failed (exit $rc); see $out/corpus.json"
[ -f "$out/corpus.json" ] || fail "the corpus test wrote no corpus.json: it was skipped"

# 4. Nothing ran.
queue="$(curl -fsS "$url/queue")"
history="$(curl -fsS "$url/history")"
python3 - "$queue" "$history" <<'PY' || fail "ComfyUI queued or ran something: queue $queue, history ${history:0:300}"
import json, sys
queue, history = json.loads(sys.argv[1]), json.loads(sys.argv[2])
sys.exit(1 if queue["queue_running"] or queue["queue_pending"] or history else 0)
PY
echo "corpus: PASS, nothing queued or run; results in $out"
