#!/usr/bin/env bash
# Clear the previous answers, and derive the expected ones (and the index the
# check reads citations from) from the comfyrelay image under test.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
mkdir -p "$HARNESS_DATA/workspace/results"
rm -f "$HARNESS_DATA/workspace/results/T6.json"
"$HARNESS_DIR/tasks/T6/derive.sh" >/dev/null
