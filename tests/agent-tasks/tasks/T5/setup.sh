#!/usr/bin/env bash
# Every template ComfyUI's index tags "Image Upscale" gets the input images it
# names, as 512x384 stand-ins, so that models, nodes and partner APIs decide
# which can run. Then mark /history and clear the previous report.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy setup-t5
