#!/bin/bash
set -e

# Check if post-install steps have already been run
echo "Doing post install steps"
if [ -f .post_install_done ]; then
    echo "Post-install steps already completed."
    exit 0
fi

# This is a workaround.
if [ ! -d "$BASE_DIRECTORY/custom_nodes/ComfyUI-Manager" ]; then
    echo "Installing ComfyUI-Manager..."
    git clone --branch 3.33.8 --depth 1 https://github.com/Comfy-Org/ComfyUI-Manager.git ${BASE_DIRECTORY}/custom_nodes/ComfyUI-Manager
else
    echo "ComfyUI-Manager already installed"
fi

# Mark completion
touch .post_install_done

echo "Post-install steps completed successfully."