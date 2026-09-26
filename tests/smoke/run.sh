#!/usr/bin/env bash
# Boot smoke test for a core-cpu image. It tests our packaging, not ComfyUI:
# the image boots, drops to an arbitrary UID and GID, that user can write to
# every volume root, and no node class went missing against a published
# baseline. No workflow runs.
#
#   tests/smoke/run.sh [--network MODE] [--out DIR] [--baseline IMAGE]... <image>
#
#   --network MODE    passed to `docker run` (default: Docker's default bridge).
#                     Use `host` on a machine without a docker0 bridge.
#   --out DIR         where results go (default: tests/smoke/results, gitignored)
#   --baseline IMAGE  a published image to compare node classes against. Repeat
#                     it to give fallbacks; the first that exists is pulled.
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
#   4. Save GET /object_info, keys sorted. No comfy_extras module may fail to
#      import.
#   5. With --baseline: boot the baseline the same way and diff node classes
#      into node-diff.md. Same ComfyUI version: any baseline class missing
#      here fails. Different version (a pin bump): the diff is a report only.
#      A baseline that cannot be looked up or pulled fails; one that does not
#      exist yet (no published image) is skipped with a notice.
#   6. On any failure, print the container logs and exit 1.
#
# Every HTTP call runs inside a container, with the curl and jq the runtime
# image ships, so the host needs only Docker and nothing depends on ports.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"

usage() { sed -n '7,15p' "$0" | sed 's/^# \{0,1\}//'; }

network=""
out="$here/results"
baselines=()
image=""
while [ $# -gt 0 ]; do
  case "$1" in
    --network) network="${2:?--network needs a value}"; shift 2 ;;
    --network=*) network="${1#*=}"; shift ;;
    --out) out="${2:?--out needs a value}"; shift 2 ;;
    --baseline) baselines+=("${2:?--baseline needs a value}"); shift 2 ;;
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
name_base="$name-baseline"

fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }
label() { docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.version"}}' "$1"; }

docker image inspect "$image" >/dev/null 2>&1 \
  || fail "image $image is not loaded; \`make smoke\` builds one from this tree"
version="$(label "$image")"
[ -n "$version" ] || fail "$image has no org.opencontainers.image.version label"

mkdir -p "$out"
rm -f "$out"/object_info.json "$out"/system_stats.json "$out"/container.log \
  "$out"/baseline.log "$out"/node-diff.md "$out"/summary.json
work="$(mktemp -d "${TMPDIR:-/tmp}/comfyui-smoke.XXXXXX")"
mkdir "$work/vol"

# Root-owned throwaway containers, no network: they create the volume sources
# and, afterwards, remove what 1001 wrote into them.
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
  retire "$name" "$out/container.log" "$status"
  retire "$name_base" "$out/baseline.log" "$status"
  as_root 'rm -rf /vol/*' >/dev/null 2>&1 || true
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

# Start container $1 from image $2 as root with PUID/PGID, Manager off, extra
# `docker run` args after that; then wait for /system_stats.
boot() {
  local c="$1" img="$2" start
  shift 2
  start="$(date +%s)"
  docker run -d --name "$c" "${run_args[@]}" \
    -e PUID="$puid" -e PGID="$pgid" \
    -e COMFY_PORT="$port" \
    -e COMFY_ENABLE_MANAGER=false \
    "$@" "$img" >/dev/null
  until api "$c" /system_stats > "$work/$c.system_stats.json" 2>/dev/null; do
    if [ "$(docker inspect -f '{{.State.Running}}' "$c")" != true ]; then
      fail "$img exited (code $(docker inspect -f '{{.State.ExitCode}}' "$c")) before /system_stats answered"
    fi
    if [ $(( $(date +%s) - start )) -ge "$timeout" ]; then
      fail "$img: /system_stats did not answer within ${timeout}s"
    fi
    sleep 2
  done
  booted_in=$(( $(date +%s) - start ))
}
api() { docker exec "$1" curl -fsS --max-time 60 "http://127.0.0.1:$port$2"; }

# 1. The starting state: every volume source root:root 0755, as Docker leaves
# a missing bind-mount source. Asserted, not assumed.
as_root "cd /vol && for d in $volumes; do mkdir \$d && chown 0:0 \$d && chmod 0755 \$d; done"
mounts=()
for d in $volumes; do
  got="$(stat -c '%u:%g %a' "$work/vol/$d")"
  [ "$got" = "0:0 755" ] || fail "volume source $d starts as '$got', not '0:0 755'"
  mounts+=(-v "$work/vol/$d:/app/$d")
done

# 2. Readiness.
echo "smoke: starting $image (ComfyUI $version) as root, PUID=$puid PGID=$pgid"
boot "$name" "$image" "${mounts[@]}"
startup="$booted_in"
cp "$work/$name.system_stats.json" "$out/system_stats.json"
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

# 4. The node schema, keys sorted so two dumps diff cleanly.
api "$name" /object_info > "$work/object_info.raw.json" || fail "GET /object_info failed"
docker exec -i "$name" jq -S --arg v "$version" '{comfyui_version: $v, object_info: .}' \
  < "$work/object_info.raw.json" > "$out/object_info.json" \
  || fail "/object_info is not JSON"
nodes="$(docker exec -i "$name" jq '.object_info | length' < "$out/object_info.json")"
[ "$nodes" -gt 0 ] || fail "/object_info lists no node classes"
# A built-in node module that fails to import only logs a warning, and its
# nodes silently disappear. This is how a missing dependency shows up.
if docker logs "$name" 2>&1 | grep -E 'Cannot import .*comfy_extras'; then
  fail "a built-in comfy_extras node module failed to import"
fi
# With the host network, the baseline needs the port back.
retire "$name" "$out/container.log"

# 5. The baseline: the first candidate that exists in its registry.
baseline=""
comparison="no baseline given"
for candidate in "${baselines[@]}"; do
  if err="$(docker manifest inspect "$candidate" 2>&1 >/dev/null)"; then
    baseline="$candidate"
    break
  fi
  case "$err" in
    *"manifest unknown"*|*"no such manifest"*|*"not found"*)
      echo "smoke: baseline $candidate does not exist" ;;
    *) fail "could not look up baseline $candidate: $err" ;;
  esac
done
if [ -n "$baseline" ]; then
  echo "smoke: baseline is $baseline"
  docker pull -q "$baseline" >/dev/null || fail "could not pull baseline $baseline"
  base_version="$(label "$baseline")"
  boot "$name_base" "$baseline"
  api "$name_base" /object_info > "$work/baseline.raw.json" \
    || fail "GET /object_info failed on baseline $baseline"
  # Added and removed classes, and, for classes in both, input names that
  # appeared or went, and any other change to their input spec.
  # shellcheck disable=SC2016  # jq program
  cat "$work/baseline.raw.json" "$out/object_info.json" | docker exec -i "$name_base" jq -rs \
    --arg base "$baseline ($base_version)" --arg new "$image ($version)" '
    .[0] as $b | .[1].object_info as $n
    | ($b | keys) as $bk | ($n | keys) as $nk
    | def names($x): (($x.input.required // {}) + ($x.input.optional // {})) | keys;
      [ $bk[] | select($n[.] != null) | . as $k
        | {k: $k, plus: (names($n[$k]) - names($b[$k])), minus: (names($b[$k]) - names($n[$k])),
           other: ($n[$k].input != $b[$k].input)}
        | select(.other) ] as $changed
    | "## Node classes: \($new) vs baseline \($base)", "",
      "- \($nk | length) classes here, \($bk | length) in the baseline",
      "- Removed: \(($bk - $nk) | length)", (($bk - $nk)[] | "  - `\(.)`"),
      "- Added: \(($nk - $bk) | length)", (($nk - $bk)[] | "  - `\(.)`"),
      "- Input spec changed: \($changed | length)",
      ($changed[] | "  - `\(.k)`"
        + (if (.plus | length) > 0 then " +" + (.plus | join(" +")) else "" end)
        + (if (.minus | length) > 0 then " -" + (.minus | join(" -")) else "" end)
        + (if (.plus | length) + (.minus | length) == 0 then " (defaults, ranges or options)" else "" end))
    ' > "$out/node-diff.md" || fail "could not diff node classes against $baseline"
  removed="$(cat "$work/baseline.raw.json" "$out/object_info.json" \
    | docker exec -i "$name_base" jq -r -s '(.[0] | keys) - (.[1].object_info | keys) | .[]')"
  retire "$name_base" "$out/baseline.log"
  if [ "$base_version" = "$version" ]; then
    if [ -n "$removed" ]; then
      echo "$removed" >&2
      fail "$(echo "$removed" | wc -l) node classes in baseline $baseline are missing from this image (both ComfyUI $version)"
    fi
    comparison="no node class missing against $baseline"
  else
    comparison="ComfyUI $base_version -> $version: node diff reported in node-diff.md, not enforced"
  fi
elif [ "${#baselines[@]}" -gt 0 ]; then
  comparison="no baseline image exists yet (${baselines[*]}); comparison skipped"
  echo "::notice::smoke: $comparison"
fi
echo "smoke: $comparison"

cat > "$out/summary.json" <<EOF
{
  "image": "$image",
  "image_id": "$(docker image inspect -f '{{.Id}}' "$image")",
  "comfyui_version": "$version",
  "startup_seconds": $startup,
  "node_classes": $nodes,
  "uid_check": "passed",
  "baseline": "${baseline:-none}",
  "node_comparison": "$comparison"
}
EOF

echo "smoke: PASS in ${startup}s, $nodes node classes, results in $out"
