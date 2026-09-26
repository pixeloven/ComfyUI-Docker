#!/usr/bin/env bash
# PASS when results/T4.json (in the agent workspace) says succeeded=false,
# blames the node ComfyUI rejected, and quotes ComfyUI's per-node error type or
# message from results/T4.expected.json.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy check t4
