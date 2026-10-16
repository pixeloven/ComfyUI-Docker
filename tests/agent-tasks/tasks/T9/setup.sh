#!/usr/bin/env bash
# Fetch the tier-2 checkpoint, save workflows/t9-portrait.json (UI format,
# 512x768, 20 steps, prefix "portrait") to ComfyUI's user data through
# /userdata, overwriting an earlier run's, and mark /history and the outputs.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
fetch_tier2_model
hpy setup-tier2 T9
