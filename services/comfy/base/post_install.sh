#!/bin/bash
set -e

# Check if post-install steps have already been run
echo "Doing post install steps"
if [ -f .post_install_done ]; then
    echo "Post-install steps already completed."
    exit 0
fi

# Set default values for environment variables
if [ -z "$COMFY_PORT" ]; then
    echo "[WARNING] COMFY_PORT is not set, using default 8188"
    COMFY_PORT=8188
fi

if [ -z "$COMFY_BASE_DIRECTORY" ]; then
    echo "[WARNING] COMFY_BASE_DIRECTORY is not set, using default /data/config/comfy"
    COMFY_BASE_DIRECTORY="/data/config/comfy"
fi

if [ ! -d "${COMFY_BASE_DIRECTORY}" ]; then
    mkdir -vp ${COMFY_BASE_DIRECTORY}
fi

if [ -z "$COMFY_OUTPUT_DIRECTORY" ]; then
    echo "[WARNING] COMFY_OUTPUT_DIRECTORY is not set, using default /output"
    COMFY_OUTPUT_DIRECTORY="/output"
fi

if [ ! -d "${COMFY_OUTPUT_DIRECTORY}" ]; then
    mkdir -vp ${COMFY_OUTPUT_DIRECTORY}
fi

# This is a workaround. Installing it in the image causes the data to be lost when mounting the volume.
if [ ! -d "$COMFY_BASE_DIRECTORY/custom_nodes/ComfyUI-Manager" ]; then
    echo "Installing ComfyUI-Manager..."
    git clone --branch 3.33.8 --depth 1 https://github.com/Comfy-Org/ComfyUI-Manager.git ${COMFY_BASE_DIRECTORY}/custom_nodes/ComfyUI-Manager
else
    echo "ComfyUI-Manager already installed"
fi

# Mark completion
touch .post_install_done

echo "Post-install steps completed successfully."