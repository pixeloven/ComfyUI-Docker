#!/usr/bin/env bash
# comfyrelay, this repo's own MCP sidecar (#103), from a locally built image.
# `up` starts it on 127.0.0.1:$COMFYRELAY_PORT/mcp (default 9200) and waits
# for it; `down` removes it.
#
# The image is COMFYRELAY_IMAGE, default ghcr.io/pixeloven/comfyui/mcp:local:
# build it from the checkout under test with
# `IMAGE_LABEL=local docker buildx bake mcp --load` (on a host without a
# docker0 bridge, `docker buildx build --network host` with bake's args). It is
# never pulled, so a run tests the checkout: CI never publishes the `local`
# label.
#
# It runs as the image ships it, hardened the way tests/relay/run.sh runs it:
# an arbitrary UID, a read-only root filesystem (with a tmpfs on /tmp for
# mcp-convert, whose browser needs it), no-new-privileges. The bearer
# token is COMFYRELAY_MCP_TOKEN (lib.sh keeps one per HARNESS_DATA), and it binds
# loopback only, so under --network host nothing else on the network reaches
# it. COMFYUI_MCP_PROFILES is the image default (read,run) unless set.
set -euo pipefail
. "$(dirname "$0")/../lib.sh"

IMAGE="${COMFYRELAY_IMAGE:-ghcr.io/pixeloven/comfyui/mcp:local}"
PORT="${COMFYRELAY_PORT:-9200}"
NAME="$HARNESS_CONTAINER-mcp-comfyrelay"

case "${1:-}" in
  up)
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker image inspect "$IMAGE" >/dev/null 2>&1 || {
      echo "no image $IMAGE; build it with: IMAGE_LABEL=local docker buildx bake mcp --load" >&2
      exit 1
    }
    # Under --network host a second server on the port would answer for us.
    if [ "$(curl -s --max-time 3 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/mcp" || true)" != "000" ]; then
      echo "something already answers on 127.0.0.1:$PORT; set COMFYRELAY_PORT to a free port" >&2
      exit 1
    fi
    profiles=()
    [ -n "${COMFYUI_MCP_PROFILES:-}" ] && profiles=(-e COMFYUI_MCP_PROFILES="$COMFYUI_MCP_PROFILES")
    # An image that converts (mcp-convert) needs a writable /tmp for its browser
    # (runtime-contract.md, The mcp-convert Image), as tests/relay/run.sh gives it.
    tmp=()
    case "$(docker image inspect -f '{{json .Config.Env}}' "$IMAGE")" in
      *'"COMFYUI_MCP_CONVERT=1"'*) tmp=(--tmpfs /tmp) ;;
    esac
    docker run -d --name "$NAME" --network host \
      --user 12345:0 --read-only "${tmp[@]}" --security-opt no-new-privileges:true \
      -e COMFYUI_MCP_HTTP_TOKEN="$COMFYRELAY_MCP_TOKEN" \
      -e COMFYUI_URL="$COMFY_URL" \
      -e MCP_HOST=127.0.0.1 -e MCP_PORT="$PORT" \
      -e COMFYUI_MCP_INSTANCE_ID=harness \
      "${profiles[@]}" \
      "$IMAGE" >/dev/null
    for _ in $(seq 60); do
      # Any HTTP answer from /mcp (a 401 without the token) means it is listening.
      code="$(curl -s --max-time 3 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/mcp" || true)"
      [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" = true ] || break
      [ "$code" != "000" ] && exit 0
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
