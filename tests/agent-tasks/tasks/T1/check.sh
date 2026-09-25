#!/usr/bin/env bash
# PASS when a /history entry that is new since setup completed, its graph has
# ImageInvert, and it saved a t1_* PNG that is 256x256 and inverted (the input
# is dark on the left, so the output must be bright on the left).
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy check t1
