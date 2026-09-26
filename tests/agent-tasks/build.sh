#!/usr/bin/env bash
# Build the pinned core-cpu image locally, from the same inputs bake uses.
#
# This is two plain `docker build`s rather than `docker buildx bake core-cpu`,
# because bake has no per-target way to pass `--network host`, which hosts
# without a docker0 bridge need. COMFYUI_VERSION is read from docker-bake.hcl,
# so the pin stays in one place.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

COMFYUI_VERSION="$(bake_pin)"
[ -n "$COMFYUI_VERSION" ] || { echo "could not read COMFYUI_VERSION from docker-bake.hcl" >&2; exit 1; }
echo "Building $HARNESS_IMAGE (ComfyUI $COMFYUI_VERSION)"

docker build --network host \
  -f "$HARNESS_REPO/services/runtime/dockerfile.cpu.runtime" \
  -t "$HARNESS_RUNTIME_IMAGE" \
  "$HARNESS_REPO/services/runtime"

docker build --network host \
  --build-context "runtime=docker-image://$HARNESS_RUNTIME_IMAGE" \
  --build-arg RUNTIME=cpu \
  --build-arg TORCH_INDEX=cpu \
  --build-arg "COMFYUI_VERSION=$COMFYUI_VERSION" \
  -f "$HARNESS_REPO/services/comfy/core/dockerfile.comfy.core" \
  -t "$HARNESS_IMAGE" \
  "$HARNESS_REPO/services/comfy/core"
