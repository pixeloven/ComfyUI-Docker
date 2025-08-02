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
install_custom_node "ComfyUI_UltimateSDUpscale" "comfyui_ultimatesdupscale"

# ComfyUI-RMBG
# @description: Background removal models and nodes for clean image extraction
# @link: https://github.com/1038lab/ComfyUI-RMBG
install_custom_node "ComfyUI-RMBG" "comfyui-rmbg"

# ComfyUI-IC-Light
# @description: Advanced lighting and relighting for images with IC-Light models
# @link: https://github.com/huchenlei/ComfyUI-IC-Light
install_custom_node "ComfyUI-IC-Light" "comfyui-ic-light"

log_success "Image enhancers installation completed successfully" 