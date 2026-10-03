#!/usr/bin/env bash
# Clear the previous answers, and derive the expected ones: T6's, from the
# comfyrelay image under test (tasks/T6/derive.sh), then T6-neutral's key from
# them, which for q1 also accepts the spelling this instance's own templates
# use (see harness.py, T6_NEUTRAL).
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
mkdir -p "$HARNESS_DATA/workspace/results"
rm -f "$HARNESS_DATA/workspace/results/T6-neutral.json"
"$HARNESS_DIR/tasks/T6/derive.sh" >/dev/null
hpy derive-t6-neutral >/dev/null
