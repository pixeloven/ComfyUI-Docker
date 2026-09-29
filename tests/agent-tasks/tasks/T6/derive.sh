#!/usr/bin/env bash
# Regenerate answers.json from the comfyrelay image under test: copy its index
# to results/T6-corpus.sqlite, and take each answer from the page its question
# names. answers.json is derived, never hand-edited. The image is $1, else
# COMFYRELAY_IMAGE, else comfyrelay:latest.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy derive-t6 "${1:-}"
