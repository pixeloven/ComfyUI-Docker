#!/bin/bash
set -e

# ComfyUI-TeaCache
# @description: TeaCache is a cache for ComfyUI that is not part of the official ComfyUI repository.
# @link: https://github.com/welltop-cn/ComfyUI-TeaCache.git
if [ ! -d "$COMFY_BASE_DIRECTORY/custom_nodes/ComfyUI-TeaCache" ]; then
    echo "Installing ComfyUI-TeaCache..."
    git clone --branch main --depth 1 https://github.com/welltop-cn/ComfyUI-TeaCache.git ${COMFY_BASE_DIRECTORY}/custom_nodes/ComfyUI-TeaCache
else
    echo "ComfyUI-TeaCache already installed"
fi

# @todo let's use the manager cli to do this instead. 
# TeaCache, HiDiffusion, Sage, Flash, etc
# Note worthy https://github.com/chengzeyi/Comfy-WaveSpeed