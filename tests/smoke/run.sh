#!/usr/bin/env bash
# Boot smoke test for a core-cpu image. It tests our packaging, not ComfyUI:
# the image boots, drops to an arbitrary UID and GID, that user can write to
# every volume root, and no built-in node went missing. No workflow runs.
#
#   tests/smoke/run.sh [--network MODE] [--out DIR] [--snapshot] <image>
#
#   --network MODE  passed to `docker run` (default: Docker's default bridge).
#                   Use `host` on a machine without a docker0 bridge.
#   --out DIR       where results go (default: tests/smoke/results, gitignored)
#   --snapshot      also write schemas/comfyui/object_info.json (cpu images only)
#
# Env: SMOKE_PORT (default 8188), SMOKE_TIMEOUT in seconds (default 300).
#
# Steps, each fatal:
#   1. Bind-mount all seven volume roots from directories created root:root
#      0755 (checked), as Docker creates a missing Compose bind-mount source,
#      then start the image as root with PUID=1001 PGID=1001 and Manager off.
#      Only that path runs the entrypoint's volume chown; `docker run -u`
#      takes the non-root path and never does.
#   2. Poll /system_stats until it answers, and record the startup time.
#   3. ComfyUI (PID 1) runs as 1001:1001 (all four UID and GID fields), each
#      volume root is 1001:1001 on the host, 1001 can write to each, and the
#      comfyui.db ComfyUI created is 1001:1001.
#   4. Save GET /object_info, keys sorted, under a header naming the version.
#      When the image is the pinned ComfyUI, no node class in the committed
#      snapshot may be missing, and no comfy_extras module may fail to import.
#   5. On any failure, print the container logs and exit 1.
#
# Every HTTP call runs inside the container, with the curl and jq the runtime
# image ships, so the host needs only Docker and nothing depends on ports.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
committed="$repo/schemas/comfyui/object_info.json"

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
volumes="models custom_nodes datasets input output temp user"
name="comfyui-smoke-$$"

fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }

docker image inspect "$image" >/dev/null 2>&1 \
  || fail "image $image is not loaded; \`make smoke\` builds one from this tree"
version="$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.version"}}' "$image")"
[ -n "$version" ] || fail "$image has no org.opencontainers.image.version label"
if [ "$snapshot" = true ]; then
  runtime="$(docker image inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$image" | sed -n 's/^COMFY_RUNTIME=//p')"
  [ "$runtime" = cpu ] || fail "--snapshot is for a cpu image (generated_from: core-cpu); $image has COMFY_RUNTIME=${runtime:-unset}"
fi
pin="$(sed -n '/^variable "COMFYUI_VERSION"/,/^}/s/^ *default *= *"\(.*\)"/\1/p' "$repo/docker-bake.hcl")"

mkdir -p "$out"
rm -f "$out/object_info.json" "$out/system_stats.json" "$out/container.log" "$out/summary.json"
work="$(mktemp -d "${TMPDIR:-/tmp}/comfyui-smoke.XXXXXX")"
mkdir "$work/vol"

# Root-owned throwaway containers, no network: they create the volume sources
# and, afterwards, remove what 1001 wrote into them.
as_root() {
  docker run --rm --pull never --network none --user 0 --entrypoint sh \
    -v "$work/vol:/vol" "$image" -c "$1"
}

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
  as_root 'rm -rf /vol/*' >/dev/null 2>&1 || true
  rm -rf "$work" 2>/dev/null || echo "note: could not remove $work" >&2
  exit "$status"
}
trap cleanup EXIT

# 1. The starting state: every volume source root:root 0755, as Docker leaves
# a missing bind-mount source. Asserted, not assumed.
as_root "cd /vol && for d in $volumes; do mkdir \$d && chown 0:0 \$d && chmod 0755 \$d; done"
mounts=()
for d in $volumes; do
  got="$(stat -c '%u:%g %a' "$work/vol/$d")"
  [ "$got" = "0:0 755" ] || fail "volume source $d starts as '$got', not '0:0 755'"
  mounts+=(-v "$work/vol/$d:/app/$d")
done

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

echo "smoke: starting $image (ComfyUI $version) as root, PUID=$puid PGID=$pgid"
start="$(date +%s)"
docker run -d --name "$name" "${run_args[@]}" \
  -e PUID="$puid" -e PGID="$pgid" \
  -e COMFY_PORT="$port" \
  -e COMFY_ENABLE_MANAGER=false \
  "${mounts[@]}" \
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

# 3. The UID and GID contract. PID 1 is ComfyUI once the exec chain finishes.
# Real, effective, saved and filesystem IDs must all be PUID/PGID: a gosu to
# the wrong group, or one that never dropped, still passes a write check.
ids="$(docker exec "$name" awk '/^(Uid|Gid):/ {print $1, $2, $3, $4, $5}' /proc/1/status)"
want="$(printf 'Uid: %s %s %s %s\nGid: %s %s %s %s' "$puid" "$puid" "$puid" "$puid" "$pgid" "$pgid" "$pgid" "$pgid")"
[ "$ids" = "$want" ] || fail "ComfyUI runs with $(echo "$ids" | tr '\n' ' ')instead of $puid:$pgid"
for d in $volumes; do
  got="$(stat -c '%u:%g' "$work/vol/$d")"
  [ "$got" = "$puid:$pgid" ] || fail "volume root /app/$d is $got after startup; the entrypoint did not chown it to $puid:$pgid"
done
# shellcheck disable=SC2016  # expanded by the container's sh, not here
docker exec -u "$puid:$pgid" "$name" sh -c '
  for d in '"$volumes"'; do
    f="/app/$d/.smoke-write-test"
    { : > "$f" && rm "$f"; } || { echo "cannot write to /app/$d" >&2; exit 1; }
  done' || fail "UID $puid cannot write to every volume root"
db="$(stat -c '%u:%g' "$work/vol/user/comfyui.db" 2>/dev/null)" \
  || fail "ComfyUI did not create /app/user/comfyui.db"
[ "$db" = "$puid:$pgid" ] || fail "ComfyUI created comfyui.db as $db, not $puid:$pgid"
echo "smoke: ComfyUI runs as $puid:$pgid, owns and writes all seven volume roots, and wrote comfyui.db as $db"

# 4. The node schema. Header fields sort ahead of object_info.
api /object_info > "$work/object_info.raw.json" || fail "GET /object_info failed"
docker exec -i "$name" jq -S --arg v "$version" \
  '{comfyui_version: $v, generated_from: "core-cpu", object_info: .}' \
  < "$work/object_info.raw.json" > "$out/object_info.json" \
  || fail "/object_info is not JSON"
nodes="$(docker exec -i "$name" jq '.object_info | length' < "$out/object_info.json")"
[ "$nodes" -gt 0 ] || fail "/object_info lists no node classes"

# A built-in node module that fails to import only logs a warning, and its
# nodes silently disappear. This is how a missing dependency shows up.
if docker logs "$name" 2>&1 | grep -E 'Cannot import .*comfy_extras'; then
  fail "a built-in comfy_extras node module failed to import"
fi
# Same ComfyUI as the committed snapshot: every node class it lists must still
# be here. A pin bump skips this, and CI's snapshot job flags the stale file.
snap_version="$(docker exec -i "$name" jq -r '.comfyui_version' < "$committed" 2>/dev/null || true)"
if [ "$version" = "$pin" ] && [ "$version" = "$snap_version" ]; then
  missing="$(cat "$committed" "$out/object_info.json" \
    | docker exec -i "$name" jq -rs '(.[0].object_info | keys) - (.[1].object_info | keys) | .[]')"
  if [ -n "$missing" ]; then
    echo "$missing" >&2
    fail "$(echo "$missing" | wc -l) node classes in schemas/comfyui/object_info.json are missing from this image"
  fi
  echo "smoke: every node class in the committed snapshot is present"
else
  echo "smoke: node comparison skipped: image is $version, pin is $pin, snapshot is ${snap_version:-missing}"
fi

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
  cp "$out/object_info.json" "$committed"
  echo "smoke: wrote schemas/comfyui/object_info.json"
fi

echo "smoke: PASS in ${startup}s, $nodes node classes, results in $out"
