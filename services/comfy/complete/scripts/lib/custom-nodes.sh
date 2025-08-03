#!/bin/bash

# Custom Nodes Installation Library for ComfyUI Docker Scripts
# Source this file in your scripts to access custom node installation functions
# Usage: source "$(dirname "$0")/lib/custom-nodes.sh" || source ./scripts/custom-nodes.sh

# Function to find installed custom node directory with fuzzy matching
find_installed_node_directory() {
    local node_identifier="$1"
    local base_dir="$COMFY_BASE_DIRECTORY/custom_nodes"
    
    # Try exact lowercase match first
    local directory_name=$(echo "$node_identifier" | tr '[:upper:]' '[:lower:]')
    local directory="$base_dir/$directory_name"
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
    local core_name=$(echo "$node_identifier" | sed 's/^[Cc]omfy[Uu][Ii]-//g' | tr '[:upper:]' '[:lower:]')
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

# Function to install a custom node using ComfyUI CLI
install_custom_node() {
    local name="$1"
    local node_identifier="$2"
    # ComfyUI CLI installs nodes with lowercase names, so convert for directory check
    local directory_name=$(echo "$node_identifier" | tr '[:upper:]' '[:lower:]')
    local expected_directory="$COMFY_BASE_DIRECTORY/custom_nodes/$directory_name"
    
    # Check if already installed using fuzzy matching
    if should_skip_installation "$name" "$node_identifier"; then
        exit 0
    fi
    
    # Store list of existing directories before installation
    local existing_dirs=$(ls -1 "$COMFY_BASE_DIRECTORY/custom_nodes/" 2>/dev/null | sort)
    
    # Install using ComfyUI CLI
    log_info "Installing $name using ComfyUI CLI..."
    
    # ComfyUI CLI installs to workspace, which is symlinked to volume
    # Add verbose output and capture both stdout and stderr
    log_info "Running: comfy --workspace=\"$COMFY_APP_DIRECTORY\" node install \"$node_identifier\""
    comfy --workspace="$COMFY_APP_DIRECTORY" node install "$node_identifier" 2>&1
    local exit_code=$?
    
    log_info "ComfyUI CLI exit code: $exit_code"
    
    if [ $exit_code -eq 0 ]; then
        # Try to find the installed directory using fuzzy matching
        local found_directory=$(find_installed_node_directory "$node_identifier")
        
        if [ -n "$found_directory" ] && [ -d "$found_directory" ]; then
            log_success "$name installed successfully at: $(basename "$found_directory")"
        else
            # Show what directories were added since installation started
            log_error "ComfyUI CLI reported success but $name not found"
            log_warning "Expected at: $expected_directory"
            log_warning "Newly created directories:"
            local new_dirs=$(ls -1 "$COMFY_BASE_DIRECTORY/custom_nodes/" 2>/dev/null | sort)
            local added_dirs=$(comm -13 <(echo "$existing_dirs") <(echo "$new_dirs") | head -5)
            if [ -n "$added_dirs" ]; then
                echo "$added_dirs" | while read -r dir; do
                    log_warning "  - $dir"
                done
            else
                log_warning "  (no new directories detected)"
            fi
            log_warning "Consider using install_custom_node_from_git for this node if CLI installation consistently fails"
            log_warning "All available directories:"
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
    
    # Check if already installed using fuzzy matching
    if should_skip_installation "$repo_name" "$repo_name"; then
        exit 0
    fi
    
    # Install using git clone (use default branch)
    log_info "Installing $repo_name via git clone from: $git_url"
    git clone --depth 1 "$git_url" "$directory" --recursive
    local exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        # Verify installation using fuzzy matching
        local found_directory=$(find_installed_node_directory "$repo_name")
        if [ -n "$found_directory" ] && [ -d "$found_directory" ]; then
            # Check if requirements.txt exists and install dependencies if present
            if [ -f "$found_directory/requirements.txt" ]; then
                log_info "Installing $repo_name requirements..."
                pip install -r "$found_directory/requirements.txt"
                exit_code=$?
                if [ $exit_code -ne 0 ]; then
                    log_error "Failed to install $repo_name requirements"
                    exit 1
                fi
            else
                log_info "$repo_name has no requirements.txt file"
            fi
            log_success "$repo_name installed successfully at: $(basename "$found_directory")"
        else
            log_error "Git clone completed but $repo_name not found at expected location"
            log_warning "Expected at: $directory"
            exit 1
        fi
    else
        log_error "Failed to clone $repo_name repository from: $git_url"
        exit 1
    fi
}

# Check if functions are being sourced correctly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "This file should be sourced, not executed directly."
    echo "Usage: source \"\$(dirname \"\$0\")/lib/custom-nodes.sh\""
    exit 1
fi 