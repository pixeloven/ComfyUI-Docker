#!/bin/bash
set -e

# Source logging functions
source "$(dirname "$0")/../logging.sh"

log_info "Initializing directory structure and environment variables..."

# @todo these warning checks should probably done in the entrypoint.sh script. consider organizing the scripts into categories such as "pre-install", "post-install", "startup", "entrypoint", etc.
# Set default values for environment variables
if [ -z "$COMFY_PORT" ]; then
    log_warning "COMFY_PORT is not set, using default 8188"
    COMFY_PORT=8188
fi

if [ -z "$COMFY_BASE_DIRECTORY" ]; then
    log_warning "COMFY_BASE_DIRECTORY is not set, using default /data/config/comfy"
    COMFY_BASE_DIRECTORY="/data/config/comfy"
fi

if [ ! -d "${COMFY_BASE_DIRECTORY}" ]; then
    log_info "Creating base directory: ${COMFY_BASE_DIRECTORY}"
    mkdir -vp ${COMFY_BASE_DIRECTORY}
fi

if [ -z "$COMFY_OUTPUT_DIRECTORY" ]; then
    log_warning "COMFY_OUTPUT_DIRECTORY is not set, using default /output"
    COMFY_OUTPUT_DIRECTORY="/output"
fi

if [ ! -d "${COMFY_OUTPUT_DIRECTORY}" ]; then
    log_info "Creating output directory: ${COMFY_OUTPUT_DIRECTORY}"
    mkdir -vp ${COMFY_OUTPUT_DIRECTORY}
fi

log_success "Directory structure initialization completed"