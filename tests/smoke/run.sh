#!/usr/bin/env bash
# Boot smoke test for a core-cpu image. It tests our packaging, not ComfyUI:
# the image boots, drops to an arbitrary UID, and that UID can write where
# ComfyUI saves. No workflow runs.
#
#   tests/smoke/run.sh [--network MODE] [--out DIR] [--snapshot] <image>
#
#   --network MODE  passed to `docker run` (default: Docker's default bridge).
#                   Use `host` on a machine without a docker0 bridge.
#   --out DIR       where results go (default: tests/smoke/results, gitignored)
#   --snapshot      also write schemas/comfyui/object_info.json
#
# Env: SMOKE_PORT (default 8188), SMOKE_TIMEOUT in seconds (default 300).
#
# Steps, each fatal:
#   1. Start the image as root with PUID=1001 PGID=1001, the way Compose does.
#      Only that path runs the entrypoint's volume chown; `docker run -u`
#      takes the non-root path and never does. /app/output is bind-mounted
#      from a directory Docker creates, so it starts root:root 0755, as a
#      missing Compose bind-mount source does. Manager is off.
#   2. Poll /system_stats until it answers, and record the startup time.
#   3. ComfyUI (PID 1) runs as 1001, and UID 1001 can write to /app/output.
#   4. Save GET /object_info, keys sorted, under a header naming the version.
#   5. On any failure, print the container logs and exit 1.
#
# Every HTTP call runs inside the container, with the curl and jq the runtime
# image ships, so the host needs only Docker and nothing depends on ports.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"

usage() { sed -n '6,13p' "$0" | sed 's/^# \{0,1\}//'; }

network=""
out="$here/results"
snapshot=false
image=""
while [ $# -gt 0 ]; do
  case "$1" in
    --network) network="${2:?--network needs a value}"; shift 2 ;;
    --network=*) network="${1#*=}"; shift ;;
    --out) out="${2:?--out needs a value}"; shift 2 ;;
    --snapshot) snapshot=true; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) usage >&2; exit 2 ;;
    *) [ -z "$image" ] || { usage >&2; exit 2; }; image="$1"; shift ;;
  esac
done
[ -n "$image" ] || { usage >&2; exit 2; }

port="${SMOKE_PORT:-8188}"
timeout="${SMOKE_TIMEOUT:-300}"
puid=1001
pgid=1001
name="comfyui-smoke-$$"

fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }

docker image inspect "$image" >/dev/null 2>&1 \
  || fail "image $image is not loaded; build it first (make core-cpu)"
version="$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.version"}}' "$image")"
[ -n "$version" ] || fail "$image has no org.opencontainers.image.version label"

mkdir -p "$out"
rm -f "$out/object_info.json" "$out/system_stats.json" "$out/container.log" "$out/summary.json"
work="$(mktemp -d "${TMPDIR:-/tmp}/comfyui-smoke.XXXXXX")"

cleanup() {
  local status=$?
  if docker container inspect "$name" >/dev/null 2>&1; then
    docker logs "$name" > "$out/container.log" 2>&1 || true
    if [ "$status" -ne 0 ]; then
      echo "---- container logs ($name) ----" >&2
      cat "$out/container.log" >&2
    fi
    docker rm -f "$name" >/dev/null 2>&1 || true
  fi
  # After the chown, output/ belongs to 1001, so remove it as root, in a
  # throwaway container that needs no network.
  if [ -e "$work/output" ]; then
    docker run --rm --pull never --network none --user 0 --entrypoint rm \
      -v "$work:/work" "$image" -rf /work/output >/dev/null 2>&1 || true
  fi
  rm -rf "$work" 2>/dev/null || echo "note: could not remove $work" >&2
  exit "$status"
}
trap cleanup EXIT

run_args=(--security-opt no-new-privileges:true)
if [ -n "$network" ]; then
  run_args+=(--network "$network")
fi
if [ "$network" = host ]; then
  # On the host network, a ComfyUI already on this port would answer in
  # place of ours, and the default --listen would expose ours on every host
  # interface. Refuse the first, bind loopback for the second.
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    fail "something already listens on 127.0.0.1:$port; stop it or set SMOKE_PORT"
  fi
  run_args+=(-e "CLI_ARGS=--listen 127.0.0.1")
fi

api() { docker exec "$name" curl -fsS --max-time 60 "http://127.0.0.1:$port$1"; }

# 1. Start as root, the Compose path.
echo "smoke: starting $image (ComfyUI $version) as root, PUID=$puid PGID=$pgid"
start="$(date +%s)"
docker run -d --name "$name" "${run_args[@]}" \
  -e PUID="$puid" -e PGID="$pgid" \
  -e COMFY_PORT="$port" \
  -e COMFY_ENABLE_MANAGER=false \
  -v "$work/output:/app/output" \
  "$image" >/dev/null

# 2. Readiness.
until api /system_stats > "$out/system_stats.json" 2>/dev/null; do
  if [ "$(docker inspect -f '{{.State.Running}}' "$name")" != true ]; then
    fail "container exited (code $(docker inspect -f '{{.State.ExitCode}}' "$name")) before /system_stats answered"
  fi
  if [ $(( $(date +%s) - start )) -ge "$timeout" ]; then
    fail "/system_stats did not answer within ${timeout}s"
  fi
  sleep 2
done
startup=$(( $(date +%s) - start ))
echo "smoke: /system_stats answered after ${startup}s"

# 3. The UID contract. PID 1 is ComfyUI once the exec chain finishes; if gosu
# never dropped privileges it is still root, and root can write anywhere.
uid="$(docker exec "$name" awk '/^Uid:/ {print $2}' /proc/1/status)"
[ "$uid" = "$puid" ] || fail "ComfyUI runs as UID $uid, not PUID $puid"
docker exec -u "$puid:$pgid" "$name" \
  sh -c 'f=/app/output/.smoke-write-test && : > "$f" && rm "$f"' \
  || fail "UID $puid cannot write to /app/output; the entrypoint's volume chown did not take"
echo "smoke: ComfyUI runs as $puid, and $puid can write to /app/output"

# 4. The node schema. Header fields sort ahead of object_info.
api /object_info > "$work/object_info.raw.json" || fail "GET /object_info failed"
docker exec -i "$name" jq -S --arg v "$version" \
  '{comfyui_version: $v, generated_from: "core-cpu", object_info: .}' \
  < "$work/object_info.raw.json" > "$out/object_info.json" \
  || fail "/object_info is not JSON"
nodes="$(docker exec -i "$name" jq '.object_info | length' < "$out/object_info.json")"
[ "$nodes" -gt 0 ] || fail "/object_info lists no node classes"

cat > "$out/summary.json" <<EOF
{
  "image": "$image",
  "image_id": "$(docker image inspect -f '{{.Id}}' "$image")",
  "comfyui_version": "$version",
  "startup_seconds": $startup,
  "node_classes": $nodes,
  "uid_check": "passed"
}
EOF

if [ "$snapshot" = true ]; then
  mkdir -p "$repo/schemas/comfyui"
  cp "$out/object_info.json" "$repo/schemas/comfyui/object_info.json"
  echo "smoke: wrote schemas/comfyui/object_info.json"
fi

echo "smoke: PASS in ${startup}s, $nodes node classes, results in $out"
