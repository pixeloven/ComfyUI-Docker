#!/bin/bash
set -e

# @todo let's use the manager cli to do this instead. 
# TeaCache, HiDiffusion, Sage, Flash, etc

# ComfyUI-KJNodes
# @description: KJNodes is a collection of nodes for ComfyUI that are not part of the official ComfyUI repository.
# @link: https://github.com/kijai/ComfyUI-KJNodes
if [ ! -d "$COMFY_BASE_DIRECTORY/custom_nodes/ComfyUI-KJNodes" ]; then
    echo "Installing ComfyUI-KJNodes..."
    git clone --branch main --depth 1 https://github.com/kijai/ComfyUI-KJNodes.git ${COMFY_BASE_DIRECTORY}/custom_nodes/ComfyUI-KJNodes
else
    echo "ComfyUI-KJNodes already installed"
fi
