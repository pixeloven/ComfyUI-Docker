#!/usr/bin/env bash
# Regenerate answers.json from the ground-truth dump (results/object_info.json).
# answers.json is derived, never hand-edited. A diff after a ComfyUI bump is the
# signal that a default moved.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy derive-t3
