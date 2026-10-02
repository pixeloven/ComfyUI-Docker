#!/usr/bin/env bash
# Plant an empty pack (only the template's dev-check.sh and its .env) on the
# custom_nodes volume as t7_pack, link the workspace's pack/ to it, and restart
# ComfyUI so nothing an earlier run left registered survives. Then mark
# /history and the container's start time.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy setup-t7-pack T7
docker restart "$HARNESS_CONTAINER" >/dev/null
wait_ready 300
hpy setup-t7-mark T7 "$HARNESS_CONTAINER"
