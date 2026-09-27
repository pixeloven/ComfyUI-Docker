#!/usr/bin/env bash
# Inverted T2 (#103): start from a ComfyUI without the pack, as T2 does, and
# mark /history, the custom_nodes volume and the container's start time, so the
# check sees any change, a restart included.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
"$HARNESS_DIR/tasks/T2/reset.sh"
hpy setup-t2-refuse "$HARNESS_CONTAINER"
