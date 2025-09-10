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

# Set environment variable defaults first
if [ -z "$COMFY_DATA_DIRECTORY" ]; then
    log_warning "COMFY_DATA_DIRECTORY defaulting to /data"
    export COMFY_DATA_DIRECTORY="/data"
fi

if [ -z "$COMFY_BASE_DIRECTORY" ]; then
    log_warning "COMFY_BASE_DIRECTORY defaulting to $COMFY_DATA_DIRECTORY/comfy"
    export COMFY_BASE_DIRECTORY="$COMFY_DATA_DIRECTORY/comfy"
fi

if [ -z "$COMFY_OUTPUT_DIRECTORY" ]; then
    log_warning "COMFY_OUTPUT_DIRECTORY defaulting to $COMFY_BASE_DIRECTORY/output"
    export COMFY_OUTPUT_DIRECTORY="$COMFY_BASE_DIRECTORY/output"
fi

if [ -z "$COMFY_APP_DIRECTORY" ]; then
    log_warning "COMFY_APP_DIRECTORY defaulting to /home/comfy/app"
    export COMFY_APP_DIRECTORY="/home/comfy/app"
fi

# Ensure persistent volume directories exist with proper ownership
if [ ! -d "$COMFY_DATA_DIRECTORY" ]; then
    log_info "Creating data directory at $COMFY_DATA_DIRECTORY..."
    mkdir -vp "$COMFY_DATA_DIRECTORY"
    chown -R comfy:comfy "$COMFY_DATA_DIRECTORY"
fi

if [ ! -d "$COMFY_BASE_DIRECTORY" ]; then
    log_info "Creating ComfyUI persistent directory structure at $COMFY_BASE_DIRECTORY..."
    mkdir -vp "$COMFY_BASE_DIRECTORY"/{custom_nodes,input,models,output,temp,user}
    # mkdir -vp "$COMFY_BASE_DIRECTORY"/models/{checkpoints,vae,loras,embeddings,hypernetworks,controlnet,clip_vision,upscale_models,ipadapter}
    chown -R comfy:comfy "$COMFY_BASE_DIRECTORY"
    log_success "Created persistent volume structure"
else
    log_info "Persistent volume structure already exists at $COMFY_BASE_DIRECTORY"
fi

# Ensure all required subdirectories exist (even if base directory exists)
log_info "Ensuring all required subdirectories exist..."
mkdir -p "$COMFY_BASE_DIRECTORY"/{custom_nodes,input,models,output,temp,user}
chown -R comfy:comfy "$COMFY_DATA_DIRECTORY"


# Ensure all required symlinks exist and are correct
log_info "Validating and ensuring required symlinks..."

ensure_symlink "$COMFY_APP_DIRECTORY/custom_nodes" "$COMFY_BASE_DIRECTORY/custom_nodes" "custom nodes" || exit 1
ensure_symlink "$COMFY_APP_DIRECTORY/input" "$COMFY_BASE_DIRECTORY/input" "input" || exit 1
ensure_symlink "$COMFY_APP_DIRECTORY/models" "$COMFY_BASE_DIRECTORY/models" "models" || exit 1
ensure_symlink "$COMFY_APP_DIRECTORY/output" "$COMFY_BASE_DIRECTORY/output" "output" || exit 1
ensure_symlink "$COMFY_APP_DIRECTORY/temp" "$COMFY_BASE_DIRECTORY/temp" "temp" || exit 1
ensure_symlink "$COMFY_APP_DIRECTORY/user" "$COMFY_BASE_DIRECTORY/user" "user" || exit 1

log_success "Volume-based directory structure initialization completed"
