#!/bin/bash
set -e

# Source logging functions
source "$(dirname "$0")/../logging.sh"

# Source custom nodes installation functions
source "$(dirname "$0")/../custom-nodes.sh"

# @todo move/add workflows to the volume. I'd also like scripts to be under there too
# data/pixeloven/workflows and scripts or something