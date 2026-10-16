#!/usr/bin/env bash
# PASS when, among the /history entries new since setup, one completed with the
# checkpoint, the prompt, 4 steps and seed 1 and saved a new 256x256 t7_ PNG,
# and a later one completed with the same checkpoint, prompt and steps, seed 2,
# and saved a new 384x256 t7_ PNG.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy check t7
