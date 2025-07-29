#!/bin/bash
set -e

# Source logging functions
source "$(dirname "$0")/../logging.sh"

log_info "Starting custom nodes installation..."

# ComfyUI-KJNodes
# @description: KJNodes is a collection of nodes for ComfyUI that are not part of the official ComfyUI repository.
# @link: https://github.com/kijai/ComfyUI-KJNodes
log_info "Checking ComfyUI-KJNodes installation..."
if [ ! -d "$COMFY_BASE_DIRECTORY/custom_nodes/ComfyUI-KJNodes" ]; then
    log_info "Installing ComfyUI-KJNodes..."
    if git clone --depth 1 https://github.com/kijai/ComfyUI-KJNodes.git ${COMFY_BASE_DIRECTORY}/custom_nodes/ComfyUI-KJNodes; then
        log_success "ComfyUI-KJNodes installed successfully"
    else
        log_error "Failed to install ComfyUI-KJNodes"
        exit 1
    fi
else
    log_info "ComfyUI-KJNodes already installed, skipping..."
fi

# ComfyUI-Inspire-Pack
# @description: Inspire Pack is a collection of nodes for ComfyUI that provide inspiration-based workflows and tools.
# @link: https://github.com/ltdrdata/ComfyUI-Inspire-Pack
log_info "Checking ComfyUI-Inspire-Pack installation..."
if [ ! -d "$COMFY_BASE_DIRECTORY/custom_nodes/ComfyUI-Inspire-Pack" ]; then
    log_info "Installing ComfyUI-Inspire-Pack..."
    if git clone --depth 1 https://github.com/ltdrdata/ComfyUI-Inspire-Pack.git ${COMFY_BASE_DIRECTORY}/custom_nodes/ComfyUI-Inspire-Pack; then
        log_success "ComfyUI-Inspire-Pack installed successfully"
    else
        log_error "Failed to install ComfyUI-Inspire-Pack"
        exit 1
    fi
else
    log_info "ComfyUI-Inspire-Pack already installed, skipping..."
fi

# ComfyUI-Impact-Pack
# @description: Impact Pack provides advanced image processing and manipulation nodes for ComfyUI.
# @link: https://github.com/ltdrdata/ComfyUI-Impact-Pack
log_info "Checking ComfyUI-Impact-Pack installation..."
if [ ! -d "$COMFY_BASE_DIRECTORY/custom_nodes/ComfyUI-Impact-Pack" ]; then
    log_info "Installing ComfyUI-Impact-Pack..."
    if git clone --depth 1 https://github.com/ltdrdata/ComfyUI-Impact-Pack.git ${COMFY_BASE_DIRECTORY}/custom_nodes/ComfyUI-Impact-Pack; then
        log_success "ComfyUI-Impact-Pack installed successfully"
    else
        log_error "Failed to install ComfyUI-Impact-Pack"
        exit 1
    fi
else
    log_info "ComfyUI-Impact-Pack already installed, skipping..."
fi

# ComfyUI-Impact-Subpack
# @description: Impact Subpack provides additional nodes that complement the main Impact Pack.
# @link: https://github.com/ltdrdata/ComfyUI-Impact-Subpack
log_info "Checking ComfyUI-Impact-Subpack installation..."
if [ ! -d "$COMFY_BASE_DIRECTORY/custom_nodes/ComfyUI-Impact-Subpack" ]; then
    log_info "Installing ComfyUI-Impact-Subpack..."
    if git clone --branch main --depth 1 https://github.com/ltdrdata/ComfyUI-Impact-Subpack.git ${COMFY_BASE_DIRECTORY}/custom_nodes/ComfyUI-Impact-Subpack; then
        log_success "ComfyUI-Impact-Subpack installed successfully"
    else
        log_error "Failed to install ComfyUI-Impact-Subpack"
        exit 1
    fi
else
    log_info "ComfyUI-Impact-Subpack already installed, skipping..."
fi

log_success "Custom nodes installation completed successfully"