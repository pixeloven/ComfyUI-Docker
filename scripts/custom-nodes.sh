#!/bin/bash

# Custom Nodes Installation Library for ComfyUI Docker Scripts
# Source this file in your scripts to access custom node installation functions
# Usage: source "$(dirname "$0")/../custom-nodes.sh" || source ./scripts/custom-nodes.sh

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
    
    # ComfyUI CLI installs to workspace, which is symlinked to volume
    comfy --workspace="$COMFY_APP_DIRECTORY" node install "$node_identifier"
    local exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        # ComfyUI CLI might install with different directory names, so check for any new directories containing the expected name
        # First check exact match
        if [ -d "$directory" ]; then
            log_success "$name installed successfully"
            return 0
        fi
        
        # Check for directories containing key parts of the name (case-insensitive)
        local found_dir=""
        local name_lower=$(echo "$name" | tr '[:upper:]' '[:lower:]')
        
        # Look for directories that might match (e.g., ComfyUI-KJNodes might become kjnodes or similar)
        for dir in "$COMFY_BASE_DIRECTORY/custom_nodes"/*; do
            if [ -d "$dir" ]; then
                local dir_name=$(basename "$dir" | tr '[:upper:]' '[:lower:]')
                # Check if directory name contains key parts of expected name
                if [[ "$dir_name" == *"kjnodes"* && "$name_lower" == *"kjnodes"* ]] || \
                   [[ "$dir_name" == *"inspire"* && "$name_lower" == *"inspire"* ]] || \
                   [[ "$dir_name" == *"impact"* && "$name_lower" == *"impact"* ]]; then
                    found_dir="$dir"
                    break
                fi
            fi
        done
        
        if [ -n "$found_dir" ]; then
            log_success "$name installed successfully (found at $(basename "$found_dir"))"
            return 0
        else
            log_error "ComfyUI CLI reported success but $name not found in persistent volume"
            log_warning "Expected: $directory"
            log_warning "Available directories:"
            ls -la "$COMFY_BASE_DIRECTORY/custom_nodes/" | head -10
            exit 1
        fi
    else
        log_error "Failed to install $name"
        exit 1
    fi
}

# Check if functions are being sourced correctly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "This file should be sourced, not executed directly."
    echo "Usage: source \"\$(dirname \"\$0\")/../custom-nodes.sh\""
    exit 1
fi 