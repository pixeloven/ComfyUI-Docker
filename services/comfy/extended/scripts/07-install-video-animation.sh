#!/bin/bash
set -e

# Source logging functions
source "$(dirname "$0")/lib/logging.sh"

# Source custom nodes installation functions
source "$(dirname "$0")/lib/custom-nodes.sh"

log_info "Starting video and animation tools installation..."

# ComfyUI-AdvancedLivePortrait
# @description: Advanced live portrait functionality for real-time face animation and expression transfer
# @link: https://github.com/PowerHouseMan/ComfyUI-AdvancedLivePortrait
install_custom_node "ComfyUI-AdvancedLivePortrait" "comfyui-advancedliveportrait"

log_success "Video and animation tools installation completed successfully" 