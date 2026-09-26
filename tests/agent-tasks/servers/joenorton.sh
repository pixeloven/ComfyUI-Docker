#!/usr/bin/env bash
# joenorton/comfyui-mcp-server, as this repo's `mcp` image packages it.
# `up` starts it (HTTP on :9000/mcp) and waits for it; `down` removes it.
#
# The image binds 0.0.0.0:9000 (the sed patch in dockerfile.comfy.mcp) with no
# authentication, so under --network host it is reachable on every host
# interface while it runs. run.sh only keeps it up for joenorton's own runs.
set -euo pipefail
. "$(dirname "$0")/../lib.sh"

IMAGE="ghcr.io/pixeloven/comfyui/mcp:2.4.1@sha256:5f8d63161719ee4fa1755087570ca5d29c5e7fb51c98ac151c58ce7ed5a2ddab"
NAME="$HARNESS_CONTAINER-mcp-joenorton"

case "${1:-}" in
  up)
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker run -d --name "$NAME" --network host \
      --security-opt no-new-privileges:true \
      -e COMFYUI_URL="$COMFY_URL" \
      "$IMAGE" >/dev/null
    for _ in $(seq 60); do
      # Any HTTP answer from /mcp (even 4xx to a bare GET) means it is listening.
      code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9000/mcp || true)"
      [ "$code" != "000" ] && exit 0
      sleep 1
    done
    echo "joenorton did not listen on :9000" >&2
    docker logs --tail 30 "$NAME" >&2
    exit 1
    ;;
  down) docker rm -f "$NAME" >/dev/null 2>&1 || true ;;
  *) echo "usage: $0 up|down" >&2; exit 2 ;;
esac
