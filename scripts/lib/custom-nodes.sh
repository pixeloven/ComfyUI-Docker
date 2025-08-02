#!/bin/bash

# Custom Nodes Installation Library for ComfyUI Docker Scripts
# Source this file in your scripts to access custom node installation functions
# Usage: source "$(dirname "$0")/../custom-nodes.sh" || source ./scripts/custom-nodes.sh

# Function to install a custom node using ComfyUI CLI
install_custom_node() {
    local name="$1"
    local node_identifier="$2"
    # ComfyUI CLI installs nodes with lowercase names, so convert for directory check
    local directory_name=$(echo "$node_identifier" | tr '[:upper:]' '[:lower:]')
    local directory="$COMFY_BASE_DIRECTORY/custom_nodes/$directory_name"
    
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
        # Check if installed (ComfyUI CLI uses lowercase directory names)
        if [ -d "$directory" ]; then
            log_success "$name installed successfully"
        else
            log_error "ComfyUI CLI reported success but $name not found at expected path: $directory"
            log_warning "Available directories:"
            ls -la "$COMFY_BASE_DIRECTORY/custom_nodes/" | head -10
            exit 1
        fi
    else
        log_error "Failed to install $name"
        exit 1
    fi
}

# Function to install a custom node from git repository
install_custom_node_from_git() {
    local repo_name="$1"
    local git_url="$2"
    # Convert repository name to lowercase for consistent directory naming
    local directory_name=$(echo "$repo_name" | tr '[:upper:]' '[:lower:]')
    local directory="$COMFY_BASE_DIRECTORY/custom_nodes/$directory_name"
    
    log_info "Checking $repo_name installation..."
    
    # Early return if already installed
    if [ -d "$directory" ]; then
        log_info "$repo_name already installed, skipping..."
        return 0
    fi
    
    # Install using git clone
    log_info "Installing $repo_name via git clone..."
    git clone --branch main --depth 1 "$git_url" "$directory" --recursive
    local exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        # Check if requirements.txt exists and install dependencies if present
        if [ -f "$directory/requirements.txt" ]; then
            log_info "Installing $repo_name requirements..."
            pip install -r "$directory/requirements.txt"
            exit_code=$?
            if [ $exit_code -ne 0 ]; then
                log_error "Failed to install $repo_name requirements"
                exit 1
            fi
        else
            log_info "$repo_name has no requirements.txt file"
        fi
        log_success "$repo_name installed successfully"
    else
        log_error "Failed to clone $repo_name repository"
        exit 1
    fi
}

# Check if functions are being sourced correctly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "This file should be sourced, not executed directly."
    echo "Usage: source \"\$(dirname \"\$0\")/../custom-nodes.sh\""
    exit 1
fi 