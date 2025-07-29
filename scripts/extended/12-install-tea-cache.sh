#!/bin/bash
set -e

# Source logging functions
source "$(dirname "$0")/../logging.sh"

# ComfyUI-TeaCache
# @description: TeaCache is a cache for ComfyUI that is not part of the official ComfyUI repository.
# @link: https://github.com/welltop-cn/ComfyUI-TeaCache.git

log_info "Checking ComfyUI-TeaCache installation..."

if [ ! -d "$COMFY_BASE_DIRECTORY/custom_nodes/ComfyUI-TeaCache" ]; then
    log_info "Installing ComfyUI-TeaCache..."
    
    # Run git clone and capture exit code, but let output show
    git clone --branch main --depth 1 https://github.com/welltop-cn/ComfyUI-TeaCache.git ${COMFY_BASE_DIRECTORY}/custom_nodes/ComfyUI-TeaCache
    local exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        log_success "ComfyUI-TeaCache installed successfully"
    else
        log_error "Failed to install ComfyUI-TeaCache"
        exit 1
    fi
else
    log_info "ComfyUI-TeaCache already installed, skipping..."
fi

# @todo let's use the manager cli to do this instead. 
# TeaCache, HiDiffusion, Sage, Flash, etc
# Note worthy https://github.com/chengzeyi/Comfy-WaveSpeed