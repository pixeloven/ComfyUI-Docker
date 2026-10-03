#!/usr/bin/env bash
# Score results/T6-neutral.json (in the agent workspace) against T6's derived
# answers for q1, q2 and q4, by answer alone: the agent's `source` note isn't
# checked. Prints N/3; PASS only at 3.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy check t6-neutral
