#!/usr/bin/env bash
# Clear the previous answers, and derive the expected ones the way T6 does, from
# the comfyrelay image under test (tasks/T6/derive.sh). The check uses q1, q2
# and q4 of them.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
mkdir -p "$HARNESS_DATA/workspace/results"
rm -f "$HARNESS_DATA/workspace/results/T6-neutral.json"
"$HARNESS_DIR/tasks/T6/derive.sh" >/dev/null
