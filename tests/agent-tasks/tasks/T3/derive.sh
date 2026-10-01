#!/usr/bin/env bash
# Derive the answers from the ground-truth dump (results/object_info.json) into
# results/T3.answers.json, which the check scores against. The committed
# answers.json is derived too, never hand-edited, and this never writes it: it
# reports a difference instead, the signal that a ComfyUI bump moved a default.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy derive-t3
