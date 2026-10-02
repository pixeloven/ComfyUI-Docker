#!/usr/bin/env bash
# Plant tasks/T7-fix/pack, a V3 pack with an import error and a wrong output
# type, on the custom_nodes volume as t7_pack, with the template's dev-check.sh
# and its .env; link the workspace's pack/ to it; restart ComfyUI so it fails to
# load it. Then mark /history and the container's start time.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy setup-t7-pack T7-fix
docker restart "$HARNESS_CONTAINER" >/dev/null
wait_ready 300
hpy setup-t7-mark T7-fix "$HARNESS_CONTAINER"
