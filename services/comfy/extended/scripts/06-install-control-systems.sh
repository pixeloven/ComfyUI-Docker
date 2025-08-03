#!/bin/bash
set -e

# Source logging functions
source "$(dirname "$0")/lib/logging.sh"

# Source custom nodes installation functions
source "$(dirname "$0")/lib/custom-nodes.sh"

log_info "Starting control systems installation..."

# ComfyUI_IPAdapter_plus
# @description: IP-Adapter Plus for advanced image prompting and conditioning with various adapter models
# @link: https://github.com/cubiq/ComfyUI_IPAdapter_plus
install_custom_node "ComfyUI_IPAdapter_plus" "comfyui_ipadapter_plus"

# comfyui_controlnet_aux
# @description: ControlNet preprocessors and auxiliary nodes for advanced image conditioning and control
# @link: https://github.com/Fannovel16/comfyui_controlnet_aux
install_custom_node "comfyui_controlnet_aux" "comfyui_controlnet_aux"

log_success "Control systems installation completed successfully" 