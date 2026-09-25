#!/usr/bin/env bash
# Stop the harness instance and any MCP server it started. Keeps results/.
# `./down.sh --purge` also deletes the scratch data directory.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

for s in "$HARNESS_DIR"/servers/*.sh; do
  "$s" down >/dev/null 2>&1 || true
done
docker rm -f "$HARNESS_CONTAINER" >/dev/null 2>&1 || true

if [ "${1:-}" = "--purge" ]; then
  # Files ComfyUI wrote are owned by $(id -u), so no sudo is needed.
  rm -rf "$HARNESS_DATA"
  echo "removed $HARNESS_DATA"
fi
