#!/usr/bin/env bash
# Fetch the tier-2 checkpoint, put the broken graph (four faults: a misspelled
# checkpoint, a missing required input, a bad COMBO value, a CLIP output wired
# into a VAE input) in the agent workspace, submit it once to confirm ComfyUI
# reports each fault, and mark /history and the output files.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
fetch_tier2_model
hpy setup-tier2 T8
