#!/usr/bin/env bash
# Remove ComfyUI-Custom-Scripts from the custom_nodes volume, whatever it was
# installed as, and restart ComfyUI so its nodes leave /object_info.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"

shopt -s nullglob nocaseglob
for d in "$HARNESS_DATA"/custom_nodes/*; do
  [ -d "$d" ] || continue
  if grep -qs 'name = "comfyui-custom-scripts"' "$d/pyproject.toml" \
     || [[ "$(basename "$d")" == comfyui-custom-scripts* ]]; then
    echo "removing $d"
    rm -rf "$d"
  fi
done

docker restart "$HARNESS_CONTAINER" >/dev/null
wait_ready 300
