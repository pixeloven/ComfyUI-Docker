#!/usr/bin/env bash
# artokun/comfyui-mcp, pinned on npm, over streamable HTTP with a bearer token.
# `up` starts it on 127.0.0.1:9100/mcp and waits; `down` stops it.
#
# Pinned for a fixed evaluation: auto-update off (it otherwise `npm install`s
# itself at startup) and panel auto-install off (it otherwise writes its own
# custom node into ComfyUI). HOME and the npm cache live on the scratch volume,
# so nothing is installed globally and the operator's own comfyui-mcp config
# cannot leak in.
#
# The evaluation scores the full tool surface (the owner's call on #102).
# ARTOKUN_TOOL_PRESET=safe or =readonly restricts it; `safe` withholds
# install_custom_node, create_workflow (node_info and validate) and
# upload_image, so under it T2 cannot pass; see README.
set -euo pipefail
. "$(dirname "$0")/../lib.sh"

VERSION="0.52.203"
PORT=9100
HOME_DIR="$HARNESS_DATA/artokun-home"
PIDFILE="$RESULTS/artokun.pid"

case "${1:-}" in
  up)
    "$0" down
    mkdir -p "$HOME_DIR"
    preset="${ARTOKUN_TOOL_PRESET:-}"
    env_args=(
      HOME="$HOME_DIR"
      npm_config_cache="$HOME_DIR/.npm"
      npm_config_update_notifier=false
      MCP_TRANSPORT=http
      MCP_HOST=127.0.0.1
      MCP_PORT="$PORT"
      COMFYUI_MCP_HTTP_TOKEN="$ARTOKUN_MCP_TOKEN"
      COMFYUI_URL="$COMFY_URL"
      COMFYUI_MCP_AUTO_UPDATE_DISABLE=1
      COMFYUI_MCP_PANEL_AUTOINSTALL=0
    )
    [ -n "$preset" ] && env_args+=(COMFYUI_MCP_TOOL_PRESET="$preset")
    # Optional: let restart_comfyui reboot ComfyUI through Manager's HTTP API.
    # Against a loopback URL artokun takes its local restart path, finds no
    # process it launched, and does nothing unless COMFYUI_RESTART_COMMAND is
    # set. Manager's reboot re-execs ComfyUI in place (PID 1, the container
    # keeps running), and it drops the connection mid-reply, which is curl
    # exit 52. That is the expected outcome, not an error. No Docker access.
    if [ "${ARTOKUN_MANAGER_RESTART:-0}" = 1 ]; then
      env_args+=(COMFYUI_RESTART_COMMAND="curl -sS -o /dev/null --max-time 30 -X POST $COMFY_URL/v2/manager/reboot; rc=\$?; [ \"\$rc\" -eq 0 ] || [ \"\$rc\" -eq 52 ]")
    fi
    # setsid: its own process group, so `down` also stops the node process
    # that npx spawns (it outlives npx otherwise).
    setsid env "${env_args[@]}" npx -y "comfyui-mcp@$VERSION" \
      > "$RESULTS/artokun.log" 2>&1 < /dev/null &
    echo $! > "$PIDFILE"
    for _ in $(seq 180); do
      code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/mcp" || true)"
      [ "$code" != "000" ] && exit 0
      kill -0 "$(cat "$PIDFILE")" 2>/dev/null || break
      sleep 1
    done
    echo "artokun did not listen on :$PORT" >&2
    tail -30 "$RESULTS/artokun.log" >&2
    exit 1
    ;;
  down)
    if [ -s "$PIDFILE" ]; then
      # The pid is the setsid'd leader, so it is also the process group id.
      kill -TERM -- "-$(cat "$PIDFILE")" 2>/dev/null || true
      rm -f "$PIDFILE"
    fi
    ;;
  *) echo "usage: $0 up|down" >&2; exit 2 ;;
esac
