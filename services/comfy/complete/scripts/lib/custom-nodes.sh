#!/bin/bash

# Custom Nodes Installation Library for ComfyUI Docker Scripts
# Source this file in your scripts to access custom node installation functions
# Usage: source "$(dirname "$0")/lib/custom-nodes.sh" || source ./scripts/lib/custom-nodes.sh

# Function to find installed custom node directory with fuzzy matching
find_installed_node_directory() {
    local node_identifier="$1"
    local base_dir="/app/custom_nodes"
    
    # Try exact match first
    local directory="$base_dir/$node_identifier"
    if [ -d "$directory" ]; then
        echo "$directory"
        return 0
    fi
    
    # Try case-insensitive fuzzy matching
    local found_dir=$(find "$base_dir" -maxdepth 1 -type d -iname "*$(echo "$node_identifier" | sed 's/[^a-zA-Z0-9]//g')*" | head -1)
    if [ -n "$found_dir" ] && [ -d "$found_dir" ]; then
        echo "$found_dir"
        return 0
    fi
    
    # Try matching the core name (remove prefixes like ComfyUI-)
    local core_name=$(echo "$node_identifier" | sed 's/^[Cc]omfy[Uu][Ii]-//g')
    local core_match=$(find "$base_dir" -maxdepth 1 -type d -iname "*$core_name*" | head -1)
    if [ -n "$core_match" ] && [ -d "$core_match" ]; then
        echo "$core_match"
        return 0
    fi
    
    return 1
}

# Function to check if installation should be skipped (node already installed)
should_skip_installation() {
    local display_name="$1"
    local identifier="$2"
    
    log_info "Checking $display_name installation..."
    
    # Use fuzzy matching to check if already installed
    local found_directory=$(find_installed_node_directory "$identifier")
    if [ -n "$found_directory" ] && [ -d "$found_directory" ]; then
        log_info "$display_name already installed at: $(basename "$found_directory"), skipping..."
        return 0  # Yes, should skip installation
    fi
    
    return 1  # No, should not skip installation
}

# Function to install a custom node from git repository
install_custom_node_from_git() {
    local repo_name="$1"
    local git_url="$2"
    
    # Check if already installed using fuzzy matching
    if should_skip_installation "$repo_name" "$repo_name"; then
        return 0
    fi
    
    # Use the repository name as-is for directory naming
    local directory="/app/custom_nodes/$repo_name"
    
    # Install using git clone (use default branch)
    log_info "Installing $repo_name via git clone from: $git_url"
    git clone --depth 1 "$git_url" "$directory" --recursive
    local exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        # Verify installation
        if [ -d "$directory" ]; then
            # Check if requirements.txt exists and install dependencies if present
            if [ -f "$directory/requirements.txt" ]; then
                log_info "Installing $repo_name requirements..."
                pip install -r "$directory/requirements.txt"
                if [ $? -ne 0 ]; then
                    log_error "Failed to install $repo_name requirements"
                    log_error "Continuing with remaining nodes..."
                    return 1
                fi
            else
                log_info "$repo_name has no requirements.txt file"
            fi
            log_success "$repo_name installed successfully at: $repo_name"
        else
            log_error "Git clone completed but $repo_name directory not found"
            log_error "Continuing with remaining nodes..."
            return 1
        fi
    else
        log_error "Failed to clone $repo_name repository from: $git_url"
        log_error "Continuing with remaining nodes..."
        return 1
    fi
}

# Legacy function for backward compatibility - now uses git installation
install_custom_node() {
    local name="$1"
    local node_identifier="$2"
    
    log_warning "install_custom_node() is deprecated. Use install_custom_node_from_git() instead."
    log_error "Cannot install $name: No git URL provided for legacy CLI method"
    log_error "Please update the script to use install_custom_node_from_git with the proper GitHub URL"
    log_error "Continuing with remaining nodes..."
    return 1
}

# Check if functions are being sourced correctly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "This file should be sourced, not executed directly."
    echo "Usage: source \"\$(dirname \"\$0\")/lib/custom-nodes.sh\""
    exit 1
fi 