#!/usr/bin/env bash
# Stop the harness instance and any MCP server it started. Keeps results/.
# `./down.sh --purge` also deletes the scratch data the harness created: the
# directories listed in $HARNESS_DATA/.harness-created (volume directories
# up.sh made, the agent workspace, and external.sh's bin/ for the stdio client)
# and the external agents' token files (comfyrelay's and artokun's), then
# $HARNESS_DATA if that leaves it empty. A
# directory the harness found rather than made, such as a real models/ mounted
# on purpose, is never removed.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

for s in "$HARNESS_DIR"/servers/*.sh; do
  "$s" down >/dev/null 2>&1 || true
done
stop_stdio_clients
docker rm -f "$HARNESS_CONTAINER" >/dev/null 2>&1 || true

if [ "${1:-}" = "--purge" ]; then
  # Files ComfyUI wrote are owned by $(id -u), so no sudo is needed.
  for d in $HARNESS_VOLUMES workspace bin; do
    [ -e "$HARNESS_DATA/$d" ] || continue
    if grep -qxF "$d" "$HARNESS_CREATED" 2>/dev/null; then
      rm -rf "${HARNESS_DATA:?}/$d"
    else
      echo "not removing $HARNESS_DATA/$d: the harness didn't create it" >&2
    fi
  done
  rm -f "$HARNESS_CREATED" "$COMFYRELAY_TOKEN_FILE" "$ARTOKUN_TOKEN_FILE"
  rmdir "$HARNESS_DATA" 2>/dev/null || true
  echo "removed what the harness created in $HARNESS_DATA"
fi
