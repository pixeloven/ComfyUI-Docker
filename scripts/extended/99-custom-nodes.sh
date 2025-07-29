#!/bin/bash
set -e

# ComfyUI-KJNodes
# @description: KJNodes is a collection of nodes for ComfyUI that are not part of the official ComfyUI repository.
# @link: https://github.com/kijai/ComfyUI-KJNodes
if [ ! -d "$COMFY_BASE_DIRECTORY/custom_nodes/ComfyUI-KJNodes" ]; then
    echo "Installing ComfyUI-KJNodes..."
    git clone --branch main --depth 1 https://github.com/kijai/ComfyUI-KJNodes.git ${COMFY_BASE_DIRECTORY}/custom_nodes/ComfyUI-KJNodes
else
    echo "ComfyUI-KJNodes already installed"
fi

# ComfyUI-Inspire-Pack
# @description: Inspire Pack is a collection of nodes for ComfyUI that provide inspiration-based workflows and tools.
# @link: https://github.com/ltdrdata/ComfyUI-Inspire-Pack
if [ ! -d "$COMFY_BASE_DIRECTORY/custom_nodes/ComfyUI-Inspire-Pack" ]; then
    echo "Installing ComfyUI-Inspire-Pack..."
    git clone --branch main --depth 1 https://github.com/ltdrdata/ComfyUI-Inspire-Pack.git ${COMFY_BASE_DIRECTORY}/custom_nodes/ComfyUI-Inspire-Pack
else
    echo "ComfyUI-Inspire-Pack already installed"
fi

# ComfyUI-Impact-Pack
# @description: Impact Pack provides advanced image processing and manipulation nodes for ComfyUI.
# @link: https://github.com/ltdrdata/ComfyUI-Impact-Pack
if [ ! -d "$COMFY_BASE_DIRECTORY/custom_nodes/ComfyUI-Impact-Pack" ]; then
    echo "Installing ComfyUI-Impact-Pack..."
    git clone --branch main --depth 1 https://github.com/ltdrdata/ComfyUI-Impact-Pack.git ${COMFY_BASE_DIRECTORY}/custom_nodes/ComfyUI-Impact-Pack
else
    echo "ComfyUI-Impact-Pack already installed"
fi

# ComfyUI-Impact-Subpack
# @description: Impact Subpack provides additional nodes that complement the main Impact Pack.
# @link: https://github.com/ltdrdata/ComfyUI-Impact-Subpack
if [ ! -d "$COMFY_BASE_DIRECTORY/custom_nodes/ComfyUI-Impact-Subpack" ]; then
    echo "Installing ComfyUI-Impact-Subpack..."
    git clone --branch main --depth 1 https://github.com/ltdrdata/ComfyUI-Impact-Subpack.git ${COMFY_BASE_DIRECTORY}/custom_nodes/ComfyUI-Impact-Subpack
else
    echo "ComfyUI-Impact-Subpack already installed"
fi