#!/usr/bin/env bash
# Place the broken workflow (a MASK wired into SaveImage's IMAGE input) in the
# agent workspace, submit it once ourselves, and keep ComfyUI's real /prompt
# error in results/T4.expected.json for the check to compare against.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy setup-t4
