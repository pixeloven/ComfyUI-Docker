#!/usr/bin/env bash
# Custom-node dependency test for a core-cpu image (#115): a node pack's Python
# packages, installed the way a user installs them, survive a container
# recreate, and land in the node venv on the user volume, never in the image's
# venv. It also checks the Manager settings startup.sh writes (#125).
#
#   tests/smoke/node-deps.sh [--network MODE] [--out DIR] <image>
#
#   --network MODE    passed to `docker run` (default: Docker's default bridge).
#                     Use `host` on a machine without a docker0 bridge.
#   --out DIR         where logs go (default: tests/smoke/results, gitignored)
#
# Env: SMOKE_PORT (default 8188), SMOKE_TIMEOUT in seconds (default 300).
# Needs the network: the Comfy Registry, GitHub and PyPI.
#
# Steps, each fatal:
#   1. Bind-mount custom_nodes and user from directories created root:root
#      0755, with a Manager config.ini already on the user volume, as a Manager
#      that ran before leaves it: use_uv = True and share_option = none.
#   2. Start the image as root with PUID=1001 PGID=1001 and Manager on.
#      Startup must have set use_uv = False and kept share_option.
#   3. As 1001, in a `docker exec` session, `cm-cli install` the registry pack
#      comfyui-image-saver@1.26.1, whose one dependency is piexif. piexif must
#      import from the node venv.
#   4. Restart. `Image Saver` is in /object_info and the pack didn't fail to
#      import.
#   5. Recreate on the same volumes, started directly as non-root 1001:1001
#      (the Kubernetes path), with COMFY_MANAGER_SECURITY_LEVEL=strong. Step
#      4's checks pass again, piexif still imports from the node venv, the
#      config says security_level = strong, and Manager's reboot route answers
#      403.
#   6. Neither container changed anything under /app/.venv (`docker diff`).
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
pack="comfyui-image-saver@1.26.1"
node_class="Image Saver"
node_venv=/app/user/__node_venv
config=/app/user/__manager/config.ini
name="comfyui-node-deps-$$"

fail() { echo "NODE-DEPS FAIL: $*" >&2; exit 1; }

docker image inspect "$image" >/dev/null 2>&1 \
  || fail "image $image is not loaded; \`make smoke\` builds one from this tree"

mkdir -p "$out"
rm -f "$out"/node-deps-*.log
work="$(mktemp -d "${TMPDIR:-/tmp}/comfyui-node-deps.XXXXXX")"
mkdir "$work/vol"

as_root() {
  docker run --rm --pull never --network none --user 0 --entrypoint sh \
    -v "$work/vol:/vol" "$image" -c "$1"
}

# Save a container's logs, print them if the run is failing, and remove it.
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
  retire "$name" "$out/node-deps-$stage.log" "$status"
  as_root 'rm -rf /vol/*' >/dev/null 2>&1 || true
  rm -rf "$work" 2>/dev/null || echo "note: could not remove $work" >&2
  exit "$status"
}
stage=1
trap cleanup EXIT

run_args=(--security-opt no-new-privileges:true)
if [ -n "$network" ]; then
  run_args+=(--network "$network")
fi
if [ "$network" = host ]; then
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    fail "something already listens on 127.0.0.1:$port; stop it or set SMOKE_PORT"
  fi
  run_args+=(-e "CLI_ARGS=--listen 127.0.0.1")
fi

api() { docker exec "$name" curl -fsS --max-time 60 "http://127.0.0.1:$port$1"; }
as_user() { docker exec -u 1001:1001 "$name" "$@"; }

# Wait for /system_stats on the running container.
ready() {
  local start
  start="$(date +%s)"
  until api /system_stats >/dev/null 2>&1; do
    if [ "$(docker inspect -f '{{.State.Running}}' "$name")" != true ]; then
      fail "the container exited (code $(docker inspect -f '{{.State.ExitCode}}' "$name")) before /system_stats answered"
    fi
    if [ $(( $(date +%s) - start )) -ge "$timeout" ]; then
      fail "/system_stats did not answer within ${timeout}s"
    fi
    sleep 2
  done
}

# The pack's nodes are loaded, and its dependency comes from the node venv.
check_pack() {
  api /object_info > "$work/object_info.json" || fail "GET /object_info failed"
  docker exec -i "$name" jq -e --arg c "$node_class" 'has($c)' < "$work/object_info.json" >/dev/null \
    || fail "'$node_class' is not in /object_info ($1)"
  if docker logs "$name" 2>&1 | grep -E 'IMPORT FAILED.*comfyui-image-saver|Cannot import .*comfyui-image-saver'; then
    fail "comfyui-image-saver failed to import ($1)"
  fi
  local where
  where="$(as_user python -c 'import piexif; print(piexif.__file__)')" \
    || fail "piexif does not import ($1)"
  case "$where" in
    "$node_venv"/*) ;;
    *) fail "piexif imports from $where, not from $node_venv ($1)" ;;
  esac
  echo "node-deps: '$node_class' loaded, piexif from $where ($1)"
}

# Nothing under /app/.venv changed in this container's writable layer.
check_image_venv() {
  local changed
  changed="$(docker diff "$name" | awk '$2 == "/app/.venv" || index($2, "/app/.venv/") == 1')"
  [ -z "$changed" ] || { echo "$changed" >&2; fail "the image venv changed ($1)"; }
}

setting() { as_user sh -c "sed -n 's/^$1 *= *//p' $config"; }

# 1. Volume sources, and a config.ini as a Manager that ran before leaves it.
as_root "cd /vol && mkdir custom_nodes user && chmod 0755 custom_nodes user \
  && mkdir user/__manager \
  && printf '[default]\nuse_uv = True\nshare_option = none\n' > user/__manager/config.ini \
  && chown -R 1001:1001 user/__manager"
mounts=(-v "$work/vol/custom_nodes:/app/custom_nodes" -v "$work/vol/user:/app/user")

# 2. Root start, PUID/PGID 1001.
echo "node-deps: starting $image as root, PUID=1001 PGID=1001, Manager on"
docker run -d --name "$name" "${run_args[@]}" -e PUID=1001 -e PGID=1001 \
  -e COMFY_PORT="$port" "${mounts[@]}" "$image" >/dev/null
ready
[ "$(setting use_uv)" = False ] || fail "startup left use_uv = '$(setting use_uv)' in $config"
[ "$(setting share_option)" = none ] || fail "startup did not keep share_option in $config"
echo "node-deps: startup set use_uv = False and kept the rest of config.ini"

# 3. Install the pack as a user would, in a docker exec session.
as_user cm-cli install "$pack" --user-directory /app/user/__manager > "$out/node-deps-install.log" 2>&1 \
  || { cat "$out/node-deps-install.log" >&2; fail "cm-cli install $pack failed"; }
grep -q 'INSTALLED.*comfyui-image-saver' "$out/node-deps-install.log" \
  || { cat "$out/node-deps-install.log" >&2; fail "cm-cli did not report $pack as installed"; }

# 4. Restart to load it.
docker restart -t 3 "$name" >/dev/null
ready
check_pack "after install and restart"
check_image_venv "root start"
retire "$name" "$out/node-deps-1.log"

# 5. Recreate on the same volumes, as non-root 1001:1001.
stage=2
echo "node-deps: recreating as non-root 1001:1001 on the same volumes"
docker run -d --name "$name" "${run_args[@]}" --user 1001:1001 \
  -e COMFY_PORT="$port" -e COMFY_MANAGER_SECURITY_LEVEL=strong "${mounts[@]}" "$image" >/dev/null
ready
check_pack "after recreate"
[ "$(setting security_level)" = strong ] || fail "COMFY_MANAGER_SECURITY_LEVEL=strong left security_level = '$(setting security_level)'"
code="$(docker exec "$name" curl -s -o /dev/null -w '%{http_code}' -X POST \
  -H 'Content-Type: application/json' -d '{}' "http://127.0.0.1:$port/v2/manager/reboot")"
[ "$code" = 403 ] || fail "Manager's reboot route answered $code under security_level = strong, not 403"
echo "node-deps: security_level = strong, and the reboot route answers 403"
check_image_venv "non-root start"
retire "$name" "$out/node-deps-2.log"

echo "node-deps: PASS"
