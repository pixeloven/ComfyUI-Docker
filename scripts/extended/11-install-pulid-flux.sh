#!/bin/bash
set -e

# Source logging functions
source "$(dirname "$0")/../logging.sh"

log_info "PuLID_ComfyUI_FLUX installation is currently disabled"

# # PuLID_ComfyUI_FLUX (Enhanced implementation with SDXL support)
# # @description: Enhanced PuLID implementation with additional features and SDXL support.
# # @link: https://github.com/lschaupp/PuLID_ComfyUI_FLUX
# log_info "Checking PuLID_ComfyUI_FLUX installation..."
# if [ ! -d "$COMFY_BASE_DIRECTORY/custom_nodes/PuLID_ComfyUI_FLUX" ]; then
#     log_info "Installing PuLID_ComfyUI_FLUX..."
#     if git clone --branch main --depth 1 https://github.com/lschaupp/PuLID_ComfyUI_FLUX.git ${COMFY_BASE_DIRECTORY}/custom_nodes/PuLID_ComfyUI_FLUX; then
#         log_info "Installing PuLID_ComfyUI_FLUX requirements..."
#         if pip install -r ${COMFY_BASE_DIRECTORY}/custom_nodes/PuLID_ComfyUI_FLUX/requirements.txt; then
#             log_success "PuLID_ComfyUI_FLUX installed successfully"
#         else
#             log_error "Failed to install PuLID_ComfyUI_FLUX requirements"
#             exit 1
#         fi
#     else
#         log_error "Failed to clone PuLID_ComfyUI_FLUX repository"
#         exit 1
#     fi
# else
#     log_info "PuLID_ComfyUI_FLUX already installed, skipping..."
# fi

# https://github.com/lldacing/ComfyUI_PuLID_Flux_ll - Does it support SDXL?