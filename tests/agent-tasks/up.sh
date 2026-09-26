#!/usr/bin/env bash
# Start the pinned core-cpu image for the harness, and record what is running.
#
# Host networking, Manager on (T2 installs through it), and every data volume
# on a scratch directory ($HARNESS_DATA). Writes results/instance.json.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

if docker container inspect "$HARNESS_CONTAINER" >/dev/null 2>&1; then
  echo "$HARNESS_CONTAINER already exists; run ./down.sh first" >&2
  exit 1
fi
if curl -fsS -o /dev/null "$COMFY_URL/system_stats" 2>/dev/null; then
  echo "something already answers on $COMFY_URL; refusing to start a second ComfyUI" >&2
  exit 1
fi
docker image inspect "$HARNESS_IMAGE" >/dev/null 2>&1 || "$HARNESS_DIR/build.sh"

for d in custom_nodes datasets input models output temp user; do
  mkdir -p "$HARNESS_DATA/$d"
done

# PUID/PGID follow the invoking user, so the scratch files stay removable.
#
# CLI_ARGS re-binds ComfyUI to loopback (the last --listen wins over the one
# startup.sh passes). Two reasons: with --network host the default 0.0.0.0
# would expose an unauthenticated ComfyUI on every host interface, and Manager
# refuses installs over HTTP on a non-loopback listener unless its config says
# network_mode=personal_cloud. T2 needs those installs; see README "Findings".
docker run -d --name "$HARNESS_CONTAINER" \
  --network host \
  --security-opt no-new-privileges:true \
  -e PUID="$(id -u)" -e PGID="$(id -g)" \
  -e COMFY_PORT="$COMFY_PORT" \
  -e COMFY_ENABLE_MANAGER=true \
  -e COMFY_ENABLE_ASSETS=true \
  -e CLI_ARGS="--listen 127.0.0.1" \
  -v "$HARNESS_DATA/custom_nodes:/app/custom_nodes" \
  -v "$HARNESS_DATA/datasets:/app/datasets" \
  -v "$HARNESS_DATA/input:/app/input" \
  -v "$HARNESS_DATA/models:/app/models" \
  -v "$HARNESS_DATA/output:/app/output" \
  -v "$HARNESS_DATA/temp:/app/temp" \
  -v "$HARNESS_DATA/user:/app/user" \
  -v "$HARNESS_REPO/examples/core-cpu/extra_model_paths.yaml:/app/extra_model_paths.yaml:ro" \
  "$HARNESS_IMAGE" >/dev/null

echo "Waiting for $COMFY_URL/system_stats ..."
wait_ready 300
hpy record-instance "$HARNESS_IMAGE" > "$RESULTS/instance.json"
cat "$RESULTS/instance.json"
