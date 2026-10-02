#!/usr/bin/env bash
# PASS when the container is the one setup left (StartedAt unchanged);
# /object_info/T7Reverse and /object_info/T7Show come from custom_nodes.t7_pack
# in category t7, T7Reverse STRING `text` -> STRING and T7Show an output node with
# a STRING `text`; ComfyUI's log has no import failure or comfy_entrypoint
# warning for the pack; its __init__.py defines comfy_entrypoint and no .py
# file has NODE_CLASS_MAPPINGS; pyproject.toml parses with project.name,
# project.version and tool.comfy.PublisherId; results/T7.json names a /history
# entry new since setup that completed, ran T7Reverse with text "harness" and
# showed "ssenrah"; and the check's own run of T7Reverse -> T7Show with a
# random value, kept nowhere, shows it reversed.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy check t7
