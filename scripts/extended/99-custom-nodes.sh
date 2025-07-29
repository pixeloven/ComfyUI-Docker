#!/bin/bash
set -e

# Source logging functions
source "$(dirname "$0")/../logging.sh"

# Source custom nodes installation functions
source "$(dirname "$0")/../custom-nodes.sh"

log_info "Starting custom nodes installation..."

# Custom nodes install to volume via symlink - this ensures persistence
# ComfyUI CLI installs to $COMFY_APP_DIRECTORY/custom_nodes (symlinked to $COMFY_BASE_DIRECTORY/custom_nodes)

# ComfyUI-KJNodes
# @description: KJNodes is a collection of nodes for ComfyUI that are not part of the official ComfyUI repository.
# @link: https://github.com/kijai/ComfyUI-KJNodes
install_custom_node "ComfyUI-KJNodes" "comfyui-kjnodes"

# ComfyUI-Inspire-Pack
# @description: Inspire Pack is a collection of nodes for ComfyUI that provide inspiration-based workflows and tools.
# @link: https://github.com/ltdrdata/ComfyUI-Inspire-Pack
install_custom_node "ComfyUI-Inspire-Pack" "comfyui-inspire-pack"

# ComfyUI-Impact-Pack
# @description: Impact Pack provides advanced image processing and manipulation nodes for ComfyUI.
# @link: https://github.com/ltdrdata/ComfyUI-Impact-Pack
install_custom_node "ComfyUI-Impact-Pack" "comfyui-impact-pack"

# ComfyUI-Impact-Subpack
# @description: Impact Subpack provides additional nodes that complement the main Impact Pack.
# @link: https://github.com/ltdrdata/ComfyUI-Impact-Subpack
install_custom_node "ComfyUI-Impact-Subpack" "comfyui-impact-subpack"

log_success "Custom nodes installation completed successfully"