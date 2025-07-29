#!/bin/bash
set -e

# Source logging functions
source "$(dirname "$0")/../logging.sh"

log_info "Starting custom nodes installation..."

# Function to install a custom node using ComfyUI CLI
install_custom_node() {
    local name="$1"
    local node_identifier="$2"
    local directory="$COMFY_BASE_DIRECTORY/custom_nodes/$name"
    
    log_info "Checking $name installation..."
    
    # Early return if already installed
    if [ -d "$directory" ]; then
        log_info "$name already installed, skipping..."
        return 0
    fi
    
    # Install using ComfyUI CLI
    log_info "Installing $name using ComfyUI CLI..."
    if comfy --workspace="$COMFY_APP_DIRECTORY" node install "$node_identifier"; then
        # Verify installation actually worked by checking directory exists
        if [ -d "$directory" ]; then
            log_success "$name installed successfully"
        else
            log_error "ComfyUI CLI reported success but $name directory not found at $directory"
            exit 1
        fi
    else
        log_error "Failed to install $name"
        exit 1
    fi
}

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

log_success "Custom nodes installation completed successfully"