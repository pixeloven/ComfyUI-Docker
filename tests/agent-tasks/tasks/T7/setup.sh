#!/usr/bin/env bash
# Fetch the tier-2 checkpoint (models/comfy-lock.yaml) through comfyctl fetch,
# then mark the /history entries and output files that already exist.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
fetch_tier2_model
hpy setup-tier2 T7
