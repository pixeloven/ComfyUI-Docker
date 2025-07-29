#!/bin/bash
set -e

# Source logging functions
source "$(dirname "$0")/../logging.sh"

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
if [ ! -d "$COMFY_BASE_DIRECTORY" ]; then
    log_info "Creating ComfyUI persistent directory structure at $COMFY_BASE_DIRECTORY..."
    mkdir -vp "$COMFY_BASE_DIRECTORY"/{custom_nodes,input,models,output,temp,user}
    # mkdir -vp "$COMFY_BASE_DIRECTORY"/models/{checkpoints,vae,loras,embeddings,hypernetworks,controlnet,clip_vision,upscale_models,ipadapter}
    chown -R comfy:comfy "$COMFY_DATA_DIRECTORY"
    log_success "Created persistent volume structure"
else
    log_info "Persistent volume structure already exists at $COMFY_BASE_DIRECTORY"
fi

# Ensure all required subdirectories exist (even if base directory exists)
log_info "Ensuring all required subdirectories exist..."
mkdir -p "$COMFY_BASE_DIRECTORY"/{custom_nodes,input,models,output,temp,user}
chown -R comfy:comfy "$COMFY_DATA_DIRECTORY"

# Function to ensure symlink exists and is correct
ensure_symlink() {
    local source_path="$1"
    local target_path="$2"
    local description="$3"
    
    # Remove existing symlink or file if it exists but is incorrect
    if [ -e "$source_path" ] || [ -L "$source_path" ]; then
        if [ ! -L "$source_path" ] || [ "$(readlink "$source_path")" != "$target_path" ]; then
            log_info "Removing incorrect $description symlink/file at $source_path"
            rm -rf "$source_path"
        fi
    fi
    
    # Create symlink if it doesn't exist or was removed
    if [ ! -L "$source_path" ]; then
        log_info "Creating $description symlink: $source_path -> $target_path"
        ln -sf "$target_path" "$source_path"
    fi
    
    # Validate the symlink
    if [ -L "$source_path" ] && [ -d "$target_path" ]; then
        log_success "$description symlink validated: $(basename "$source_path") -> $(basename "$target_path")"
        return 0
    else
        log_error "$description symlink validation failed"
        log_error "Source: $source_path (exists: $([ -L "$source_path" ] && echo "yes" || echo "no"))"
        log_error "Target: $target_path (exists: $([ -d "$target_path" ] && echo "yes" || echo "no"))"
        return 1
    fi
}

# Ensure all required symlinks exist and are correct
log_info "Validating and ensuring required symlinks..."

ensure_symlink "$COMFY_APP_DIRECTORY/custom_nodes" "$COMFY_BASE_DIRECTORY/custom_nodes" "custom nodes" || exit 1
ensure_symlink "$COMFY_APP_DIRECTORY/input" "$COMFY_BASE_DIRECTORY/input" "input" || exit 1
ensure_symlink "$COMFY_APP_DIRECTORY/models" "$COMFY_BASE_DIRECTORY/models" "models" || exit 1
ensure_symlink "$COMFY_APP_DIRECTORY/output" "$COMFY_BASE_DIRECTORY/output" "output" || exit 1
ensure_symlink "$COMFY_APP_DIRECTORY/temp" "$COMFY_BASE_DIRECTORY/temp" "temp" || exit 1
ensure_symlink "$COMFY_APP_DIRECTORY/user" "$COMFY_BASE_DIRECTORY/user" "user" || exit 1

log_success "Volume-based directory structure initialization completed"