#!/usr/bin/env bash
# Inverted T2 (#103): start from a ComfyUI without the pack, as T2 does, and
# mark /history and the custom_nodes volume so the check sees any change.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
"$HARNESS_DIR/tasks/T2/reset.sh"
hpy setup-t2-refuse
