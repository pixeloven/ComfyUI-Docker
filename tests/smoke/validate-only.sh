#!/usr/bin/env bash
# The validate-only opt-in (#215) on a core-cpu image: COMFY_ENABLE_VALIDATE_ONLY=true
# loads the image's module under any UID, POST /comfyrelay/validate_only answers
# as /prompt does and never queues the graph, /prompt still queues and runs, and
# without the opt-in the route doesn't exist.
#
#   tests/smoke/validate-only.sh [--network MODE] [--out DIR] <image>
#
#   --network MODE    passed to `docker run` (default: Docker's default bridge).
#                     Use `host` on a machine without a docker0 bridge.
#   --out DIR         where logs go (default: tests/smoke/results, gitignored)
#
# Env: SMOKE_PORT (default 8188), SMOKE_TIMEOUT in seconds (default 300).
#
# Steps, each fatal:
#   1. Start as root with PUID=1001 PGID=1001, Manager off and the opt-in on.
#      The module loaded. GET /comfyrelay/validate_only answers {"validate_only":
#      true}. A valid EmptyImage -> SaveImage graph POSTed to it gets /prompt's
#      200 with a prompt_id, and afterwards ComfyUI has no such job, an empty
#      queue, no history entry and no file in /app/output. A broken one gets
#      /prompt's 400 with per-node errors. The same valid graph POSTed to
#      /prompt runs and saves its file: the wrapper drops only what the route
#      sends.
#   2. Start as non-root 12345:0 (the Kubernetes path) with the opt-in on: the
#      module, root-owned in the image, loads and the route answers.
#   3. Start as root with no opt-in (the default): the module isn't loaded, the
#      GET answers 404 and the POST anything but 200, so nothing can be queued
#      through it.
#   On any failure, print the container logs and exit 1.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"

usage() { sed -n '7,13p' "$0" | sed 's/^# \{0,1\}//'; }

network=""
out="$here/results"
image=""
while [ $# -gt 0 ]; do
  case "$1" in
    --network) network="${2:?--network needs a value}"; shift 2 ;;
    --network=*) network="${1#*=}"; shift ;;
    --out) out="${2:?--out needs a value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    -*) usage >&2; exit 2 ;;
    *) [ -z "$image" ] || { usage >&2; exit 2; }; image="$1"; shift ;;
  esac
done
[ -n "$image" ] || { usage >&2; exit 2; }

port="${SMOKE_PORT:-8188}"
timeout="${SMOKE_TIMEOUT:-300}"
route=/comfyrelay/validate_only
name="comfyui-validate-only-$$"

fail() { echo "VALIDATE-ONLY FAIL: $*" >&2; exit 1; }

docker image inspect "$image" >/dev/null 2>&1 \
  || fail "image $image is not loaded; \`make smoke\` builds one from this tree"

mkdir -p "$out"
rm -f "$out"/validate-only-*.log
work="$(mktemp -d "${TMPDIR:-/tmp}/comfyui-validate-only.XXXXXX")"

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

stage=1
cleanup() {
  local status=$?
  retire "$name" "$out/validate-only-$stage.log" "$status"
  rm -rf "$work" 2>/dev/null || true
  exit "$status"
}
trap cleanup EXIT

run_args=(--security-opt no-new-privileges:true -e COMFY_PORT="$port" -e COMFY_ENABLE_MANAGER=false)
if [ -n "$network" ]; then
  run_args+=(--network "$network")
fi
if [ "$network" = host ]; then
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    fail "something already listens on 127.0.0.1:$port; stop it or set SMOKE_PORT"
  fi
  run_args+=(-e "CLI_ARGS=--listen 127.0.0.1")
fi

# The container's log so far, read whole: grep -q on a pipe under pipefail
# can fail a check it just passed.
logs() { docker logs "$name" > "$work/container.log" 2>&1; echo "$work/container.log"; }
# curl inside the container: GET $1, or POST $2 (JSON) to $1. Prints the body,
# then the HTTP status on its own last line. Never fails on a 4xx.
http() {
  if [ $# -gt 1 ]; then
    docker exec "$name" curl -sS --max-time 60 -w '\n%{http_code}' -X POST \
      -H 'Content-Type: application/json' -d "$2" "http://127.0.0.1:$port$1"
  else
    docker exec "$name" curl -sS --max-time 60 -w '\n%{http_code}' "http://127.0.0.1:$port$1"
  fi
}
status_of() { tail -n 1 <<< "$1"; }
body_of() { sed '$d' <<< "$1"; }
jqc() { docker exec -i "$name" jq "$@"; }

# Start the image with extra `docker run` args, then wait for /system_stats.
boot() {
  local start
  start="$(date +%s)"
  docker run -d --name "$name" "${run_args[@]}" "$@" "$image" >/dev/null
  until docker exec "$name" curl -fsS --max-time 10 "http://127.0.0.1:$port/system_stats" >/dev/null 2>&1; do
    if [ "$(docker inspect -f '{{.State.Running}}' "$name")" != true ]; then
      fail "$image exited (code $(docker inspect -f '{{.State.ExitCode}}' "$name")) before /system_stats answered"
    fi
    [ $(( $(date +%s) - start )) -lt "$timeout" ] || fail "/system_stats did not answer within ${timeout}s"
    sleep 2
  done
}

graph='{"prompt": {"1": {"class_type": "EmptyImage", "inputs": {"width": 64, "height": 64, "batch_size": 1, "color": 12345}},
  "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "validate_only_smoke"}}}}'
broken='{"prompt": {"1": {"class_type": "EmptyImage", "inputs": {"width": "wide", "height": 64, "batch_size": 1, "color": 0}},
  "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}}}}'

# 1. Root start, PUID/PGID 1001, opt-in on.
echo "validate-only: starting $image as root, PUID=1001, COMFY_ENABLE_VALIDATE_ONLY=true"
boot -e PUID=1001 -e PGID=1001 -e COMFY_ENABLE_VALIDATE_ONLY=true
grep -q 'comfyrelay_validate_only: installed' "$(logs)" || fail "the validate-only module did not load"
got="$(http "$route")"
[ "$(status_of "$got")" = 200 ] && [ "$(body_of "$got" | jqc -r .validate_only)" = true ] \
  || fail "GET $route answered $(status_of "$got"): $(body_of "$got")"

got="$(http "$route" "$graph")"
[ "$(status_of "$got")" = 200 ] || fail "a valid graph got HTTP $(status_of "$got") from $route: $(body_of "$got")"
id="$(body_of "$got" | jqc -r .prompt_id)"
[ -n "$id" ] && [ "$id" != null ] || fail "$route answered 200 without a prompt_id: $(body_of "$got")"
sleep 2  # a queued prompt would have started, and finished, by now
job="$(http "/api/jobs/$id")"
[ "$(status_of "$job")" = 404 ] || fail "ComfyUI has job $id from $route: $(body_of "$job")"
queue="$(body_of "$(http /queue)")"
[ "$(jqc '(.queue_running | length) + (.queue_pending | length)' <<< "$queue")" = 0 ] \
  || fail "the queue is not empty after $route: $queue"
[ "$(body_of "$(http "/history/$id")" | jqc -c .)" = '{}' ] || fail "ComfyUI's history has $id from $route"
[ -z "$(docker exec "$name" ls -A /app/output)" ] || fail "$route ran the graph: /app/output has a file"
echo "validate-only: $route accepted a valid graph, and ComfyUI queued nothing, recorded nothing and saved nothing"

got="$(http "$route" "$broken")"
[ "$(status_of "$got")" = 400 ] || fail "a broken graph got HTTP $(status_of "$got") from $route, not /prompt's 400"
types="$(body_of "$got" | jqc -c '[.node_errors[].errors[].type] | sort')"
[ "$types" = '["invalid_input_type","required_input_missing"]' ] || fail "$route's node errors are $types"
echo "validate-only: $route refused a broken graph with /prompt's node errors $types"

got="$(http /prompt "$graph")"
[ "$(status_of "$got")" = 200 ] || fail "/prompt answered HTTP $(status_of "$got") with the opt-in on"
id="$(body_of "$got" | jqc -r .prompt_id)"
start="$(date +%s)"
until [ "$(body_of "$(http "/history/$id")" | jqc -r --arg id "$id" '.[$id].status.status_str // empty')" = success ]; do
  [ $(( $(date +%s) - start )) -lt 60 ] || fail "a graph sent to /prompt with the opt-in on did not run to success"
  sleep 1
done
docker exec "$name" ls /app/output | grep -q '^validate_only_smoke' || fail "/prompt's run saved no file"
echo "validate-only: /prompt still queues and runs a graph with the opt-in on"
retire "$name" "$out/validate-only-1.log"

# 2. Non-root start, the Kubernetes path, opt-in on.
stage=2
echo "validate-only: starting as non-root 12345:0 with the opt-in on"
boot --user 12345:0 -e COMFY_ENABLE_VALIDATE_ONLY=true
grep -q 'comfyrelay_validate_only: installed' "$(logs)" || fail "the module did not load as UID 12345"
[ "$(status_of "$(http "$route")")" = 200 ] || fail "GET $route did not answer as UID 12345"
echo "validate-only: as UID 12345 the module loads and $route answers"
retire "$name" "$out/validate-only-2.log"

# 3. The default: off.
stage=3
echo "validate-only: starting as root with no opt-in"
boot -e PUID=1001 -e PGID=1001
! grep -q 'comfyrelay_validate_only' "$(logs)" || fail "the module loaded without the opt-in"
[ "$(status_of "$(http "$route")")" = 404 ] || fail "GET $route answered without the opt-in"
got="$(status_of "$(http "$route" "$graph")")"
[ "$got" != 200 ] || fail "POST $route answered 200 without the opt-in"
echo "validate-only: without the opt-in, GET $route is 404 and the POST $got"
retire "$name" "$out/validate-only-3.log"

echo "validate-only: PASS"
