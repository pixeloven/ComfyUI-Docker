#!/bin/bash
set -e

# Source logging functions
source "$(dirname "$0")/lib/logging.sh"

# Source custom nodes installation functions
source "$(dirname "$0")/lib/custom-nodes.sh"

log_info "Starting image enhancers installation..."

# ComfyUI_UltimateSDUpscale
# @description: Advanced tiled upscaling with diffusion models for high-quality image enlargement
# @link: https://github.com/ssitu/ComfyUI_UltimateSDUpscale
install_custom_node_from_git "ComfyUI_UltimateSDUpscale" "https://github.com/ssitu/ComfyUI_UltimateSDUpscale.git"

# ComfyUI-RMBG
# @description: Background removal models and nodes for clean image extraction
# @link: https://github.com/1038lab/ComfyUI-RMBG
install_custom_node_from_git "ComfyUI-RMBG" "https://github.com/1038lab/ComfyUI-RMBG.git"

# ComfyUI-IC-Light
# @description: Advanced lighting and relighting for images with IC-Light models
# @link: https://github.com/huchenlei/ComfyUI-IC-Light
install_custom_node_from_git "ComfyUI-IC-Light" "https://github.com/huchenlei/ComfyUI-IC-Light.git"

log_success "Image enhancers installation completed successfully" 