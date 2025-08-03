#!/bin/bash
set -e

# Source logging functions
source "$(dirname "$0")/lib/logging.sh"

# Source custom nodes installation functions
source "$(dirname "$0")/lib/custom-nodes.sh"

log_info "Starting object detection and segmentation installation..."

# ComfyUI-Impact-Pack
# @description: Object detection, segmentation, and selective processing with advanced masking capabilities
# @link: https://github.com/ltdrdata/ComfyUI-Impact-Pack
# Using git installation due to CLI reliability issues
install_custom_node_from_git "ComfyUI-Impact-Pack" "https://github.com/ltdrdata/ComfyUI-Impact-Pack.git"

# ComfyUI-Impact-Subpack
# @description: Additional components and utilities for ComfyUI-Impact-Pack
# @link: https://github.com/ltdrdata/ComfyUI-Impact-Subpack
install_custom_node "ComfyUI-Impact-Subpack" "comfyui-impact-subpack"

log_success "Object detection and segmentation installation completed successfully" 