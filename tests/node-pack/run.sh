#!/usr/bin/env bash
# The node-pack template's test (#107), the same script CI's node-pack job runs.
#
# It copies templates/node-pack into a scratch "pack repository" with the
# fixture pack in fixtures/good, boots core-cpu through the template's compose
# file, and drives the template's dev-check.sh through the loop a pack
# developer runs. It asserts outcomes only, never how fast a restart is:
#
#   1. the fixture loads, and a workflow using it runs;
#   2. an edit to its Python is live after dev-check.sh's restart (Manager);
#   3. an edit to its JavaScript is served with no restart;
#   4. a pack with an import error, the V1/V3 trap, and T7-fix's planted pack
#      (tests/agent-tasks/tasks/T7-fix/pack) each fail dev-check.sh;
#   5. with Manager off, dev-check.sh --no-docker-fallback fails without running
#      docker, and without the flag it restarts the container instead.
#
# CI runs it in two places: the node-pack job, against the published
# core:cpu-latest, when only the template or this test changes; and smoke-cpu,
# against the pull request's own core-cpu build, whenever the image changes
# (a ComfyUI bump included), so a ComfyUI that breaks the loop fails before merge.
#
# Settings: COMFY_IMAGE (default the template's, core:cpu-latest), COMFY_PORT
# (default 8188, published on 127.0.0.1), COMPOSE_PROJECT_NAME (default
# node-pack-test) and NODE_PACK_WORKDIR (default a new temp directory, removed
# afterwards). Needs docker compose, curl and jq.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
here="$repo_root/tests/node-pack"
template="$repo_root/templates/node-pack"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-node-pack-test}"
port="${COMFY_PORT:-8188}"
image="${COMFY_IMAGE:-}"
pack=dev-check-fixture
work="${NODE_PACK_WORKDIR:-$(mktemp -d "${TMPDIR:-/tmp}/node-pack-test.XXXXXX")}"
# The checks run against the published container; nothing here should be
# taken from the caller's environment by dev-check.sh instead of .env.
unset COMFY_URL PACK_NAME COMFY_PORT COMFY_IMAGE

step() { printf '\n### %s\n' "$*"; }
die() { echo "FAILED: $*" >&2; exit 1; }
cleanup() {
  rc=$?
  if [ "$rc" != 0 ] && [ -f "$work/docker-compose.yml" ]; then
    (cd "$work" && docker compose logs --no-color --tail 150 comfyui) >&2 || true
  fi
  [ -f "$work/docker-compose.yml" ] && (cd "$work" && docker compose down -v --remove-orphans >/dev/null 2>&1) || true
  [ -n "${NODE_PACK_WORKDIR:-}" ] || rm -rf "$work"
  exit "$rc"
}
trap cleanup EXIT

# The pack repository: the template's files, then the pack's own.
cp "$template/docker-compose.yml" "$template/dev-check.sh" "$work/"
sed -e "s/^PACK_NAME=.*/PACK_NAME=$pack/" -e "s/^COMFY_PORT=.*/COMFY_PORT=$port/" \
  -e "s/^PUID=.*/PUID=$(id -u)/" -e "s/^PGID=.*/PGID=$(id -g)/" \
  "$template/.env.example" > "$work/.env"
[ -z "$image" ] || echo "COMFY_IMAGE=$image" >> "$work/.env"
echo "COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME" >> "$work/.env"

# Replace the pack's files with a fixture's, keeping the template's.
use_pack() {
  find "$work" -mindepth 1 -maxdepth 1 \
    ! -name docker-compose.yml ! -name dev-check.sh ! -name .env -exec rm -rf {} +
  cp -r "$1/." "$work/"
}
# Run dev-check.sh from the pack repository, keeping its output in $out.
check() {
  set +e
  out="$(cd "$work" && ./dev-check.sh "$@" 2>&1)"
  rc=$?
  set -e
  printf '%s\n' "$out"
}
expect_failure() {
  local why="$1"
  shift
  check "$@"
  [ "$rc" = 1 ] || die "dev-check.sh exited $rc, want 1"
  grep -qF "$why" <<<"$out" || die "dev-check.sh didn't say: $why"
}

use_pack "$here/fixtures/good"
step "boot core-cpu through the template"
(cd "$work" && docker compose up -d)
# Say which image this run tests: the reference, its ID and its ComfyUI version.
cid="$(cd "$work" && docker compose ps -q comfyui)"
docker inspect -f 'image under test: {{.Config.Image}} ({{.Image}})' "$cid"
docker image inspect -f 'ComfyUI {{index .Config.Labels "org.opencontainers.image.version"}}' \
  "$(docker inspect -f '{{.Image}}' "$cid")"

step "1. the fixture loads, and a workflow using it runs"
check --no-restart --expect DevCheckEcho --workflow "$here/workflow.json"
[ "$rc" = 0 ] || die "dev-check.sh exited $rc"
grep -qF '"hello-v1"' <<<"$out" || die "the workflow didn't output hello-v1"

step "2. an edit to the Python is live after the loop's restart"
sed -i 's/^SUFFIX = "-v1"/SUFFIX = "-v2"/' "$work/__init__.py"
check --expect DevCheckEcho --workflow "$here/workflow.json"
[ "$rc" = 0 ] || die "dev-check.sh exited $rc"
grep -qF "restarted in place by Manager" <<<"$out" || die "Manager didn't restart ComfyUI"
grep -qF '"hello-v2"' <<<"$out" || die "the workflow didn't output hello-v2: the edit isn't live"

step "3. an edit to the JavaScript is served with no restart"
sed -i 's/served-v1/served-v2/' "$work/web/dev_check.js"
curl -fsS "http://127.0.0.1:$port/extensions/$pack/dev_check.js" | grep -qF served-v2 \
  || die "ComfyUI still serves the old dev_check.js"
echo "served-v2 is served"

step "4a. a pack with an import error fails the loop"
use_pack "$here/fixtures/broken-import"
expect_failure "Cannot import /app/custom_nodes/$pack module" --expect DevCheckEcho

step "4b. the V1/V3 trap fails the loop"
use_pack "$here/fixtures/v1-v3-trap"
expect_failure "both NODE_CLASS_MAPPINGS and comfy_entrypoint"

step "4c. T7-fix's planted pack fails the loop"
use_pack "$repo_root/tests/agent-tasks/tasks/T7-fix/pack"
expect_failure "Cannot import /app/custom_nodes/$pack module"

step "5a. with Manager off, --no-docker-fallback fails and never runs docker"
use_pack "$here/fixtures/good"
sed -i 's/^COMFY_ENABLE_MANAGER=.*/COMFY_ENABLE_MANAGER=false/' "$work/.env"
(cd "$work" && docker compose up -d)
check --no-restart   # wait until it answers, so the reboot route answers too
[ "$rc" = 0 ] || die "dev-check.sh exited $rc"
cid="$(cd "$work" && docker compose ps -q comfyui)"
started="$(docker inspect -f '{{.State.StartedAt}}' "$cid")"
# A docker on PATH that only records that it was called.
stub="$(mktemp -d "${TMPDIR:-/tmp}/node-pack-stub.XXXXXX")"
printf '#!/bin/sh\ntouch "%s/called"\nexit 1\n' "$stub" > "$stub/docker"
chmod +x "$stub/docker"
PATH="$stub:$PATH" check --no-docker-fallback --expect DevCheckEcho
[ "$rc" = 1 ] || die "dev-check.sh --no-docker-fallback exited $rc, want 1"
grep -qF -- "--no-docker-fallback is set" <<<"$out" || die "dev-check.sh didn't say why it failed"
[ ! -e "$stub/called" ] || die "dev-check.sh --no-docker-fallback ran docker"
rm -rf "$stub"
[ "$(docker inspect -f '{{.State.StartedAt}}' "$cid")" = "$started" ] || die "the container restarted"
echo "no docker call, and the container's StartedAt is unchanged"

step "5b. with Manager off and no flag, the loop restarts the container"
check --expect DevCheckEcho
[ "$rc" = 0 ] || die "dev-check.sh exited $rc"
grep -qF "reboot route answered HTTP" <<<"$out" || die "Manager's reboot route was not refused"
grep -qF "restarted the container" <<<"$out" || die "dev-check.sh didn't fall back to docker compose restart"

step "PASS"
