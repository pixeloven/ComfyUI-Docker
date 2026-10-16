#!/usr/bin/env bash
# Custom-node dependency test for a core-cpu image (#115): a node pack's Python
# packages, installed the way a user installs them, survive a container
# recreate, and land in the node venv on the user volume, never in the image's
# venv. It also checks that startup repairs the node venv, never fails on
# Manager's config.ini, and writes the Manager settings it owns (#125).
#
#   tests/smoke/node-deps.sh [--network MODE] [--out DIR] <image>
#
#   --network MODE    passed to `docker run` (default: Docker's default bridge).
#                     Use `host` on a machine without a docker0 bridge.
#   --out DIR         where logs go (default: tests/smoke/results, gitignored)
#
# Env: SMOKE_PORT (default 8188), SMOKE_TIMEOUT in seconds (default 300).
# Needs the network for the install: the Comfy Registry and PyPI. That step is
# retried, so a network blip doesn't fail the run.
#
# Steps, each fatal:
#   1. Bind-mount custom_nodes and user from directories created root:root
#      0755, with a Manager config.ini already on the user volume, as a Manager
#      that ran before leaves it: use_uv = True and share_option = none.
#   2. Start the image as root with PUID=1001 PGID=1001 and Manager on. As
#      1001, in a `docker exec` session, `cm-cli install` the registry pack
#      comfyui-image-saver@1.26.1, whose one dependency is piexif. Restart:
#      `Image Saver` is in /object_info, the pack imported, piexif imports.
#   3. Recreate on the same volumes, started directly as non-root 1001:1001
#      (the Kubernetes path), with COMFY_MANAGER_SECURITY_LEVEL=strong. The
#      pack still loads and piexif still imports: #115. Only then the how:
#      piexif comes from the node venv, ComfyUI runs from it, neither
#      container changed /app/.venv (`docker diff`), config.ini says use_uv = False and security_level = strong
#      and kept share_option, and Manager's reboot route answers 403.
#   4. A fresh user volume, owned by 1001, with a config.ini that isn't INI.
#      Start as non-root 1001:1001: startup makes the node venv, runs ComfyUI
#      from it, and only warns about the file. Then break the venv as a killed
#      first start leaves it (no .pth, no wrappers) and restart: startup
#      repairs it, and doesn't call it "made for another Python".
#   On any failure, print the container logs and exit 1.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"

usage() { sed -n '8,14p' "$0" | sed 's/^# \{0,1\}//'; }

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
pack_dir=/app/custom_nodes/comfyui-image-saver
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

stage=1
cleanup() {
  local status=$?
  retire "$name" "$out/node-deps-$stage.log" "$status"
  as_root 'rm -rf /vol/*' >/dev/null 2>&1 || true
  rm -rf "$work" 2>/dev/null || echo "note: could not remove $work" >&2
  exit "$status"
}
trap cleanup EXIT

run_args=(--security-opt no-new-privileges:true -e COMFY_PORT="$port")
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
# A docker exec session as the runtime user. COMFYUI_PATH is set here, not left
# to the image's cm-cli wrapper, so the same steps run on an image without one.
as_user() { docker exec -u 1001:1001 -e COMFYUI_PATH=/app/ComfyUI "$name" "$@"; }

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

# The pack's nodes are loaded and its dependency imports: what #115 is about.
check_loaded() {
  api /object_info > "$work/object_info.json" || fail "GET /object_info failed"
  docker exec -i "$name" jq -e --arg c "$node_class" 'has($c)' < "$work/object_info.json" >/dev/null \
    || fail "'$node_class' is not in /object_info ($1)"
  if docker logs "$name" 2>&1 | grep -E 'IMPORT FAILED.*comfyui-image-saver|Cannot import .*comfyui-image-saver'; then
    fail "comfyui-image-saver failed to import ($1)"
  fi
  as_user python -c 'import piexif' || fail "piexif does not import ($1)"
  echo "node-deps: '$node_class' loaded and piexif imports ($1)"
}

# ComfyUI (PID 1) runs from the node venv.
check_runs_from_venv() {
  as_user sh -c "tr '\\0' '\\n' < /proc/1/environ" | grep -qx "VIRTUAL_ENV=$node_venv" \
    || fail "ComfyUI does not run from $node_venv ($1)"
}

# Nothing under /app/.venv changed in a container's writable layer, as
# recorded by `docker diff` in file $1.
check_image_venv() {
  local changed
  changed="$(awk '$2 == "/app/.venv" || index($2, "/app/.venv/") == 1' "$1")"
  [ -z "$changed" ] || { echo "$changed" >&2; fail "the image venv changed ($2)"; }
}

setting() { as_user sh -c "sed -n 's/^$1 *= *//p' $config"; }

# The install needs the Comfy Registry and PyPI, so it gets three tries, and
# a failed try's half-installed pack is removed before the next.
install_pack() {
  local try
  for try in 1 2 3; do
    if as_user cm-cli install "$pack" --user-directory /app/user/__manager > "$out/node-deps-install.log" 2>&1 \
      && grep -q 'INSTALLED.*comfyui-image-saver' "$out/node-deps-install.log" \
      && as_user python -c 'import piexif' 2>/dev/null; then
      return 0
    fi
    echo "node-deps: cm-cli install $pack, try $try failed" >&2
    tail -n 20 "$out/node-deps-install.log" >&2
    as_user rm -rf "$pack_dir"
    [ "$try" -eq 3 ] || sleep $(( try * 15 ))
  done
  fail "cm-cli install $pack failed three times"
}

# 1. Volume sources, and a config.ini as a Manager that ran before leaves it.
as_root "cd /vol && mkdir custom_nodes user && chmod 0755 custom_nodes user \
  && mkdir user/__manager \
  && printf '[default]\nuse_uv = True\nshare_option = none\n' > user/__manager/config.ini \
  && chown -R 1001:1001 user/__manager"
mounts=(-v "$work/vol/custom_nodes:/app/custom_nodes" -v "$work/vol/user:/app/user")

# 2. Root start, PUID/PGID 1001; install as a user would, then restart.
echo "node-deps: starting $image as root, PUID=1001 PGID=1001, Manager on"
docker run -d --name "$name" "${run_args[@]}" -e PUID=1001 -e PGID=1001 "${mounts[@]}" "$image" >/dev/null
ready
install_pack
docker restart -t 3 "$name" >/dev/null
ready
check_loaded "after install and restart"
docker diff "$name" > "$work/diff-1"
retire "$name" "$out/node-deps-1.log"

# 3. Recreate on the same volumes, as non-root 1001:1001.
stage=2
echo "node-deps: recreating as non-root 1001:1001 on the same volumes"
docker run -d --name "$name" "${run_args[@]}" --user 1001:1001 \
  -e COMFY_MANAGER_SECURITY_LEVEL=strong "${mounts[@]}" "$image" >/dev/null
ready
check_loaded "after recreate"
where="$(as_user python -c 'import piexif; print(piexif.__file__)')"
case "$where" in
  "$node_venv"/*) ;;
  *) fail "piexif imports from $where, not from $node_venv" ;;
esac
check_runs_from_venv "after recreate"
docker diff "$name" > "$work/diff-2"
check_image_venv "$work/diff-1" "root start"
check_image_venv "$work/diff-2" "non-root start"
[ "$(setting use_uv)" = False ] || fail "startup left use_uv = '$(setting use_uv)' in $config"
[ "$(setting share_option)" = none ] || fail "startup did not keep share_option in $config"
[ "$(setting security_level)" = strong ] || fail "COMFY_MANAGER_SECURITY_LEVEL=strong left security_level = '$(setting security_level)'"
code="$(docker exec "$name" curl -s -o /dev/null -w '%{http_code}' -X POST \
  -H 'Content-Type: application/json' -d '{}' "http://127.0.0.1:$port/v2/manager/reboot")"
[ "$code" = 403 ] || fail "Manager's reboot route answered $code under security_level = strong, not 403"
echo "node-deps: piexif from $where; use_uv = False, share_option kept, security_level = strong, reboot route 403"
retire "$name" "$out/node-deps-2.log"

# 4. A fresh user volume and a config.ini that isn't INI, as non-root.
stage=3
as_root "cd /vol && mkdir user2 && mkdir user2/__manager \
  && echo 'not an ini file' > user2/__manager/config.ini && chown -R 1001:1001 user2"
echo "node-deps: starting as non-root 1001:1001 on a fresh user volume, config.ini malformed"
docker run -d --name "$name" "${run_args[@]}" --user 1001:1001 \
  -v "$work/vol/custom_nodes:/app/custom_nodes" -v "$work/vol/user2:/app/user" "$image" >/dev/null
ready
check_runs_from_venv "fresh user volume, non-root"
docker logs "$name" 2>&1 | grep -q "WARNING: could not set .* in $config" \
  || fail "startup did not warn about the malformed $config"
as_user sh -c "rm -f $node_venv/lib/python3*/site-packages/_comfyui_image.pth \
  $node_venv/bin/pip $node_venv/bin/pip3 $node_venv/bin/cm-cli $node_venv/bin/uv"
docker restart -t 3 "$name" >/dev/null
ready
check_runs_from_venv "after an interrupted first start"
as_user test -x "$node_venv/bin/cm-cli" || fail "startup did not restore $node_venv/bin/cm-cli"
if docker logs "$name" 2>&1 | grep -q 'made for Python'; then
  fail "startup called a half-made node venv one made for another Python"
fi
echo "node-deps: startup made the node venv as non-root, warned about config.ini, and repaired a half-made venv"
retire "$name" "$out/node-deps-3.log"

echo "node-deps: PASS"
