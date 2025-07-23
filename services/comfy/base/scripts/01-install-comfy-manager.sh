#!/bin/bash
set -e

# This is a workaround. Installing it in the image causes the data to be lost when mounting the volume.
if [ ! -d "$COMFY_BASE_DIRECTORY/custom_nodes/ComfyUI-Manager" ]; then
    echo "Installing ComfyUI-Manager..."
    git clone --branch 3.33.8 --depth 1 https://github.com/Comfy-Org/ComfyUI-Manager.git ${COMFY_BASE_DIRECTORY}/custom_nodes/ComfyUI-Manager
else
    echo "ComfyUI-Manager already installed"
fi