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

# ComfyUI-Easy-Use
# @description: Optimizations and integrations for commonly used ComfyUI nodes to make ComfyUI easier to use.
# @link: https://github.com/yolain/ComfyUI-Easy-Use
install_custom_node "ComfyUI-Easy-Use" "comfyui-easy-use"

# ComfyUI-RMBG
# @description: Advanced image background removal and object, face, clothes, and fashion segmentation using multiple AI models.
# @link: https://github.com/1038lab/ComfyUI-RMBG
install_custom_node "ComfyUI-RMBG" "comfyui-rmbg"

# ComfyUI-IC-Light
# @description: ComfyUI native implementation of IC-Light models for advanced lighting control and image relighting.
# @link: https://github.com/kijai/ComfyUI-IC-Light
install_custom_node "ComfyUI-IC-Light" "comfyui-ic-light"

# rgthree-comfy
# @description: Making ComfyUI more comfortable! Adds workflow control, UI improvements, context switches, and quality-of-life features.
# @link: https://github.com/rgthree/rgthree-comfy
install_custom_node "rgthree-comfy" "rgthree-comfy"

# comfyui_controlnet_aux
# @description: ComfyUI's ControlNet Auxiliary Preprocessors - comprehensive collection of all ControlNet preprocessors for advanced image conditioning.
# @link: https://github.com/Fannovel16/comfyui_controlnet_aux
install_custom_node_from_git "comfyui_controlnet_aux" "https://github.com/Fannovel16/comfyui_controlnet_aux.git"

# ComfyUI_UltimateSDUpscale
# @description: ComfyUI nodes for the Ultimate Stable Diffusion Upscale script by Coyote-A. Provides advanced tiled upscaling with diffusion models.
# @link: https://github.com/ssitu/ComfyUI_UltimateSDUpscale
install_custom_node_from_git "ComfyUI_UltimateSDUpscale" "https://github.com/ssitu/ComfyUI_UltimateSDUpscale.git"

log_success "Custom nodes installation completed successfully"