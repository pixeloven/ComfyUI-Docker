#!/usr/bin/env bash
# Clear the previous answers and re-derive the expected ones from the dump of
# the instance under test.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
mkdir -p "$HARNESS_DATA/workspace/results"
rm -f "$HARNESS_DATA/workspace/results/T3.json" "$RESULTS/T3.answers.json"
if [ -f "$RESULTS/object_info.json" ]; then
  "$HARNESS_DIR/tasks/T3/derive.sh" >/dev/null
elif [ "${HARNESS_EXTERNAL:-0}" = 1 ]; then
  echo "no $RESULTS/object_info.json to derive the answers from; run ./groundtruth.sh" >&2
  exit 1
else
  echo "no results/object_info.json; scoring against the committed answers.json" >&2
fi
