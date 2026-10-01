#!/usr/bin/env bash
# Stop the harness instance and any MCP server it started. Keeps results/.
# `./down.sh --purge` also deletes the scratch data: the volume directories
# up.sh creates and the agent workspace, then $HARNESS_DATA if that leaves it
# empty. Nothing else in $HARNESS_DATA is touched.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

for s in "$HARNESS_DIR"/servers/*.sh; do
  "$s" down >/dev/null 2>&1 || true
done
docker rm -f "$HARNESS_CONTAINER" >/dev/null 2>&1 || true

if [ "${1:-}" = "--purge" ]; then
  # Files ComfyUI wrote are owned by $(id -u), so no sudo is needed.
  for d in $HARNESS_VOLUMES workspace; do
    rm -rf "${HARNESS_DATA:?}/$d"
  done
  rmdir "$HARNESS_DATA" 2>/dev/null || true
  echo "removed the harness's directories in $HARNESS_DATA"
fi
