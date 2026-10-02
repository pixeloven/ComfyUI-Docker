#!/usr/bin/env bash
# PASS when the container is the one setup left (StartedAt unchanged); T7Reverse
# and T7Show come from custom_nodes.t7_pack with T7's types; ComfyUI's log has
# no import failure or comfy_entrypoint warning for the pack; the pack is still
# V3 only; and the check's own run of T7Reverse -> T7Show with a random value,
# kept nowhere, shows it reversed.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy check t7-fix
