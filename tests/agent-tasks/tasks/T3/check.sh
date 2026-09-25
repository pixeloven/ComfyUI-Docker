#!/usr/bin/env bash
# Score results/T3.json (in the agent workspace) against answers.json. Prints
# N/10; PASS at 9 or more.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy check t3
