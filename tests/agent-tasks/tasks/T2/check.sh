#!/usr/bin/env bash
# PASS when MathExpression|pysssss is in /object_info, the pack on the volume is
# the pinned commit (git HEAD, or registry version 1.2.5 when installed without
# .git), and a /history entry new since setup used that class, completed, and
# produced 42.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy check t2
