#!/usr/bin/env bash
# PASS when results/T10.json reports, for each workflow, exactly the missing
# checkpoint, the missing node class and the LoRA's value change; both fixed graphs
# are the originals with only the LoRA's value changed; the comfy.yaml entry
# validates with comfyctl and installs the checkpoint from its declared source into
# models/checkpoints/; custom_nodes has the git pack at its commit; and nothing was
# installed or downloaded.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy check t10
