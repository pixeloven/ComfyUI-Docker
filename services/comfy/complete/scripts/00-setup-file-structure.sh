#!/bin/bash
set -e

# Source logging functions
source "$(dirname "$0")/lib/logging.sh"

log_info "Initializing /app directory structure..."

# Ensure all required subdirectories exist in the app
# These directories will be directly mounted as volumes
log_info "Ensuring required directories exist in /app..."

mkdir -p /app/custom_nodes
mkdir -p /app/input
mkdir -p /app/models
mkdir -p /app/output
mkdir -p /app/temp
mkdir -p /app/user

# Set proper permissions
chown -R comfy:comfy /app/custom_nodes /app/input /app/models /app/output /app/temp /app/user

log_success "Directory structure initialization completed"
log_info "Directories ready for volume mounting:"
log_info "  /app/custom_nodes -> ./data/custom_nodes"
log_info "  /app/input -> ./data/input"
log_info "  /app/models -> ./data/models"
log_info "  /app/output -> ./data/output"
log_info "  /app/temp -> ./data/temp"
log_info "  /app/user -> ./data/user"