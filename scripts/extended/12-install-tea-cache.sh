#!/bin/bash
set -e

# Source logging functions
source "$(dirname "$0")/../logging.sh"

# Source custom nodes installation functions
source "$(dirname "$0")/../custom-nodes.sh"

# ComfyUI-TeaCache
# @description: TeaCache is a cache for ComfyUI that is not part of the official ComfyUI repository.
# @link: https://github.com/welltop-cn/ComfyUI-TeaCache.git
# install_custom_node "ComfyUI-TeaCache" "comfyui-teachache"

# TeaCache doesn't have a known CLI identifier, use git clone directly
install_custom_node_from_git "ComfyUI-TeaCache" "https://github.com/welltop-cn/ComfyUI-TeaCache.git"