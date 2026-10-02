#!/usr/bin/env bash
# Derive the answers from the comfyrelay image under test: copy its index to
# results/T6-docs.sqlite, take each answer from the page its question names, and
# write results/T6.answers.json, which the check scores against. The committed
# answers.json is derived too, never hand-edited, and this never writes it: it
# reports a difference instead. The image is $1, else COMFYRELAY_IMAGE, else
# ghcr.io/pixeloven/comfyui/mcp:local.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy derive-t6 "${1:-}"
