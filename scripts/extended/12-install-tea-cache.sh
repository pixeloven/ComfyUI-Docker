#!/bin/bash
set -e

# Source logging functions
source "$(dirname "$0")/../logging.sh"

# Source custom nodes installation functions
source "$(dirname "$0")/../custom-nodes.sh"

# ComfyUI-TeaCache
# @description: TeaCache is a cache for ComfyUI that is not part of the official ComfyUI repository.
# @link: https://github.com/welltop-cn/ComfyUI-TeaCache.git
# install_custom_node "ComfyUI-TeaCache" "comfyui-teachache"

# TeaCache doesn't have a known CLI identifier, use git clone directly
# This follows user preference to avoid fallback methods where possible
log_info "Checking ComfyUI-TeaCache installation..."

if [ ! -d "$COMFY_BASE_DIRECTORY/custom_nodes/ComfyUI-TeaCache" ]; then
    log_info "Installing ComfyUI-TeaCache via git clone..."
    git clone --branch main --depth 1 https://github.com/welltop-cn/ComfyUI-TeaCache.git "$COMFY_BASE_DIRECTORY/custom_nodes/ComfyUI-TeaCache"
    exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        log_success "ComfyUI-TeaCache installed successfully"
    else
        log_error "Failed to install ComfyUI-TeaCache"
        exit 1
    fi
else
    log_info "ComfyUI-TeaCache already installed, skipping..."
fi