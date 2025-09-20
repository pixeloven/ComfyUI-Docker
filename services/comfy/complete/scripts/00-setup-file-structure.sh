#!/bin/bash
set -e

# Source logging functions
source "$(dirname "$0")/lib/logging.sh"

# Function to create symlink, preserving any existing content
ensure_symlink() {
    local source_path="$1"
    local target_path="$2"
    local description="$3"
    
    # Ensure target directory exists
    mkdir -p "$target_path"
    
    # If source directory exists and has content, preserve it
    if [ -d "$source_path" ] && [ "$(ls -A "$source_path" 2>/dev/null)" ]; then
        log_info "Preserving existing $description content"
        mv "$source_path"/* "$target_path"/ 2>/dev/null || true
    fi
    
    # Remove source and create symlink
    rm -rf "$source_path"
    ln -sf "$target_path" "$source_path"
    
    log_success "$description symlink created: $(basename "$source_path") -> $(basename "$target_path")"
}

log_info "Initializing volume-based directory structure..."

# Set environment variable defaults
if [ -z "$COMFY_INSTANCE_ID" ]; then
    log_info "COMFY_INSTANCE_ID defaulting to 'comfy'"
    export COMFY_INSTANCE_ID="comfy"
fi

if [ -z "$COMFY_APP_DIRECTORY" ]; then
    log_warning "COMFY_APP_DIRECTORY defaulting to /home/comfy/app"
    export COMFY_APP_DIRECTORY="/home/comfy/app"
fi

if [ -z "$COMFY_BASE_DIRECTORY" ]; then
    log_info "COMFY_BASE_DIRECTORY defaulting to /instance"
    export COMFY_BASE_DIRECTORY="/instance"
fi

# Set shared directory for models and input
if [ -z "$COMFY_SHARED_DIRECTORY" ]; then
    log_info "COMFY_SHARED_DIRECTORY defaulting to /shared"
    export COMFY_SHARED_DIRECTORY="/shared"
fi

log_info "Instance ID: $COMFY_INSTANCE_ID"

# Create directory structure
log_info "Setting up directory structure for instance: $COMFY_INSTANCE_ID"

# Ensure instance-specific directories exist
if [ ! -d "$COMFY_BASE_DIRECTORY" ]; then
    log_info "Creating instance-specific directory structure at $COMFY_BASE_DIRECTORY..."
    mkdir -vp "$COMFY_BASE_DIRECTORY"/{custom_nodes,user,temp,output}
    log_success "Created instance-specific directory structure"
else
    log_info "Instance-specific directory structure already exists at $COMFY_BASE_DIRECTORY"
fi

# Ensure all required instance subdirectories exist
log_info "Ensuring all required instance subdirectories exist..."
mkdir -p "$COMFY_BASE_DIRECTORY"/{custom_nodes,user,temp,output}

# Shared directories should already exist (mounted from host)
if [ ! -d "$COMFY_SHARED_DIRECTORY/models" ] || [ ! -d "$COMFY_SHARED_DIRECTORY/input" ]; then
    log_warning "Shared directories not found at $COMFY_SHARED_DIRECTORY - they should be mounted from host"
fi

chown -R comfy:comfy "$COMFY_BASE_DIRECTORY"


# Create symlinks
log_info "Creating symlinks for instance: $COMFY_INSTANCE_ID"

# Instance-specific symlinks (to /instance mount)
ensure_symlink "$COMFY_APP_DIRECTORY/custom_nodes" "$COMFY_BASE_DIRECTORY/custom_nodes" "custom nodes" || exit 1
ensure_symlink "$COMFY_APP_DIRECTORY/user" "$COMFY_BASE_DIRECTORY/user" "user" || exit 1
ensure_symlink "$COMFY_APP_DIRECTORY/temp" "$COMFY_BASE_DIRECTORY/temp" "temp" || exit 1
ensure_symlink "$COMFY_APP_DIRECTORY/output" "$COMFY_BASE_DIRECTORY/output" "output" || exit 1

# Shared symlinks (to /shared mount)
ensure_symlink "$COMFY_APP_DIRECTORY/models" "$COMFY_SHARED_DIRECTORY/models" "models" || exit 1
ensure_symlink "$COMFY_APP_DIRECTORY/input" "$COMFY_SHARED_DIRECTORY/input" "input" || exit 1

log_success "Symlinks created successfully"

log_success "Volume-based directory structure initialization completed"
