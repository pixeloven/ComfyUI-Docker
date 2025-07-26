#!/bin/bash
set -e

# ComfyUI-Manager
# @description: Manager is a node that allows you to manage your ComfyUI instance. 
# This is a workaround. Installing it in the image causes the data to be lost when mounting the volume.
# @link: https://github.com/Comfy-Org/ComfyUI-Manager
if [ ! -d "$COMFY_BASE_DIRECTORY/custom_nodes/ComfyUI-Manager" ]; then
    echo "Installing ComfyUI-Manager..."
    git clone --branch 3.33.8 --depth 1 https://github.com/Comfy-Org/ComfyUI-Manager.git ${COMFY_BASE_DIRECTORY}/custom_nodes/ComfyUI-Manager
else
    echo "ComfyUI-Manager already installed"
fi
