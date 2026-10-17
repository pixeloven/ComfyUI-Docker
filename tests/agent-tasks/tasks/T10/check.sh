#!/usr/bin/env bash
# PASS when results/T10.json reports exactly each workflow's missing models, missing
# node classes and model value changes; both fixed graphs are the originals with only
# their model value changed; the comfy.yaml entries validate with comfyctl and fetch
# exactly the three missing models with a declared source, each from that source into
# its folder; custom_nodes has the git pack at its commit and the registry pack at its
# version; and nothing was run, installed or downloaded.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy check t10
