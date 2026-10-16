#!/usr/bin/env bash
# PASS when a /history entry new since setup ran the intended graph (the broken
# one with exactly its four faults fixed: every SaveImage computes what the
# intended one does, whatever the node ids), completed, and saved a new 256x256
# t8_ PNG. The detail counts the runs since setup.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy check t8
