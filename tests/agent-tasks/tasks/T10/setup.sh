#!/usr/bin/env bash
# Fetch the tier-2 checkpoint, put T10's placeholder LoRA in models/loras/sdxl/, confirm
# from ComfyUI that the instance lacks the checkpoint, the node class and the bare LoRA
# name the two workflows use, and put both workflows and comfy.yaml's schema in the
# agent workspace.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
fetch_tier2_model
hpy setup-tier2 T10
