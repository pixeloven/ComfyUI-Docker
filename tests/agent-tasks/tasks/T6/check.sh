#!/usr/bin/env bash
# Score results/T6.json (in the agent workspace) against answers.json. Each
# answer must match, and its cited path must be a page in the image's index
# that holds the answer. Prints N/4; PASS only at 4.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy check t6
