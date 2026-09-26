#!/usr/bin/env bash
# Place harness-input.png (512x384, black-to-white left to right) in the input
# volume, and mark the /history entries that already exist.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy ensure-input
hpy mark T1
