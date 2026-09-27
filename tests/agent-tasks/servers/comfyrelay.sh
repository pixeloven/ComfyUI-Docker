#!/usr/bin/env bash
# comfyrelay, this repo's own MCP sidecar (#103), from a locally built image.
# `up` starts it on 127.0.0.1:$COMFYRELAY_PORT/mcp (default 9200) and waits
# for it; `down` removes it.
#
# The image is COMFYRELAY_IMAGE, default comfyrelay:latest: build it from the
# checkout under test with `docker buildx bake comfyrelay --load` (on a host
# without a docker0 bridge, `docker buildx build --network host` with bake's
# args). It is never pulled: comfyrelay is not published before #136.
#
# It runs as the image ships it, hardened the way tests/relay/run.sh runs it:
# an arbitrary UID, a read-only root filesystem, no-new-privileges. The bearer
# token is COMFYRELAY_MCP_TOKEN (lib.sh makes one per checkout), and it binds
# loopback only, so under --network host nothing else on the network reaches
# it. COMFYUI_MCP_PROFILES is the image default (read,run) unless set.
set -euo pipefail
. "$(dirname "$0")/../lib.sh"

IMAGE="${COMFYRELAY_IMAGE:-comfyrelay:latest}"
PORT="${COMFYRELAY_PORT:-9200}"
NAME="$HARNESS_CONTAINER-mcp-comfyrelay"

case "${1:-}" in
  up)
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker image inspect "$IMAGE" >/dev/null 2>&1 || {
      echo "no image $IMAGE; build it with: docker buildx bake comfyrelay --load" >&2
      exit 1
    }
    profiles=()
    [ -n "${COMFYUI_MCP_PROFILES:-}" ] && profiles=(-e COMFYUI_MCP_PROFILES="$COMFYUI_MCP_PROFILES")
    docker run -d --name "$NAME" --network host \
      --user 12345:0 --read-only --security-opt no-new-privileges:true \
      -e COMFYUI_MCP_HTTP_TOKEN="$COMFYRELAY_MCP_TOKEN" \
      -e COMFYUI_URL="$COMFY_URL" \
      -e MCP_HOST=127.0.0.1 -e MCP_PORT="$PORT" \
      -e COMFYUI_MCP_INSTANCE_ID=harness \
      "${profiles[@]}" \
      "$IMAGE" >/dev/null
    for _ in $(seq 60); do
      # Any HTTP answer from /mcp (a 401 without the token) means it is listening.
      code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/mcp" || true)"
      [ "$code" != "000" ] && exit 0
      [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" = true ] || break
      sleep 1
    done
    echo "comfyrelay did not listen on :$PORT" >&2
    docker logs --tail 30 "$NAME" >&2 || true
    exit 1
    ;;
  down)
    # Keep its log beside the transcripts before removing it.
    if docker container inspect "$NAME" >/dev/null 2>&1; then
      docker logs "$NAME" > "$RESULTS/comfyrelay.log" 2>&1 || true
      docker rm -f "$NAME" >/dev/null 2>&1 || true
    fi
    ;;
  *) echo "usage: $0 up|down" >&2; exit 2 ;;
esac
