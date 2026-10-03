#!/usr/bin/env bash
# Remove ComfyUI-Custom-Scripts from the custom_nodes volume, whatever it was
# installed as, and restart ComfyUI so its nodes leave /object_info.
# --if-installed: restart only if there was a pack to remove (external.sh runs
# it on every `up`, so no task after a T2 inherits the pack).
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"

removed=0
shopt -s nullglob nocaseglob
for d in "$HARNESS_DATA"/custom_nodes/*; do
  [ -d "$d" ] || continue
  if grep -qs 'name = "comfyui-custom-scripts"' "$d/pyproject.toml" \
     || [[ "$(basename "$d")" == comfyui-custom-scripts* ]]; then
    echo "removing $d"
    rm -rf "$d"
    removed=1
  fi
done
[ "${1:-}" = --if-installed ] && [ "$removed" = 0 ] && exit 0

docker restart "$HARNESS_CONTAINER" >/dev/null
wait_ready 300
