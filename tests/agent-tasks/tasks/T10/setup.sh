#!/usr/bin/env bash
# Fetch the tier-2 checkpoint, put T10's placeholder models in models/loras/sdxl/ and
# models/upscale_models/esrgan/, confirm from ComfyUI that the instance lacks what the two
# workflows need (and that the stock template declares the API graph's checkpoint), and put
# both workflows and comfy.yaml's schema in the agent workspace.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
fetch_tier2_model
hpy setup-tier2 T10
