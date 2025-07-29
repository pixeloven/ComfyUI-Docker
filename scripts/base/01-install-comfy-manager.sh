#!/bin/bash
set -e

# Source logging functions
source "$(dirname "$0")/../logging.sh"

# ComfyUI-Manager
# @description: Manager is a node that allows you to manage your ComfyUI instance. 
# This is a workaround. Installing it in the image causes the data to be lost when mounting the volume.
# @link: https://github.com/Comfy-Org/ComfyUI-Manager

log_info "Checking ComfyUI-Manager installation..."

if [ ! -d "$COMFY_BASE_DIRECTORY/custom_nodes/ComfyUI-Manager" ]; then
    log_info "Installing ComfyUI-Manager..."
    
    # Run git clone and capture exit code, but let output show
    git clone --branch main --depth 1 https://github.com/Comfy-Org/ComfyUI-Manager.git ${COMFY_BASE_DIRECTORY}/custom_nodes/ComfyUI-Manager
    exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        log_success "ComfyUI-Manager installed successfully"
    else
        log_error "Failed to install ComfyUI-Manager"
        exit 1
    fi
else
    log_info "ComfyUI-Manager already installed, skipping..."
fi
