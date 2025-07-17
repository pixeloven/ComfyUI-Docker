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

# Install custom nodes from comfy-lock.yaml file if it exists
# @todo this is not working as expected feature still in early development
# if [ -f "comfy-lock.yaml" ]; then
#     echo "Installing custom nodes from comfy-lock.yaml..."
#     comfy node install-deps --deps=comfy-lock.yaml
# else
#     echo "No comfy-lock.yaml or comfy-lock.json found, skipping custom node installation"
# fi

# Install extensions
# @todo when building locally we should tag images as dev?
# @todo we can do it this way or we can auto load them into the data/config/comfy/user/default/ComfyUI-Manager/snapshots
# cp basic-snapshot.json "$BASE_DIRECTORY/user/default/ComfyUI-Manager/snapshots/basic-snapshot.json"    

# Mark completion
touch .post_install_done

echo "Post-install steps completed successfully."