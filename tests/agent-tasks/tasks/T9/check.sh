#!/usr/bin/env bash
# PASS when workflows/t9-portrait.json in ComfyUI's user data is still a
# UI-format workflow with the same nodes and links, and every widget value as
# setup saved it except the three requested changes (256x384, 4 steps, prefix
# t9_); and a /history entry new since setup ran that edited workflow,
# completed, and saved a new 256x384 t9_ PNG.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy check t9
