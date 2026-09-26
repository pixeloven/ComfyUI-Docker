#!/usr/bin/env bash
# Start T2 from a ComfyUI without the pack, and mark existing /history entries.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
"$HARNESS_DIR/tasks/T2/reset.sh"
hpy mark T2
