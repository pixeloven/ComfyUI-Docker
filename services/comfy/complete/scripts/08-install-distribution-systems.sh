#!/bin/bash
set -e

# Source logging functions
source "$(dirname "$0")/lib/logging.sh"

# Source custom nodes installation functions
source "$(dirname "$0")/lib/custom-nodes.sh"

log_info "Starting ComfyUI distribution systems installation..."

# ComfyUI-MultiGPU
# @description: Single-node multi-GPU optimization with Virtual VRAM management through DisTorch
# @features: Model layer distribution, automatic MultiGPU node creation, WanVideoWrapper integration
# @link: https://github.com/pollockjj/ComfyUI-MultiGPU
# @use_case: Maximize VRAM utilization on multi-GPU systems
log_info "Installing ComfyUI-MultiGPU for single-node multi-GPU optimization..."
install_custom_node_from_git "ComfyUI-MultiGPU" "https://github.com/pollockjj/ComfyUI-MultiGPU.git"

# ComfyUI-Distributed
# @description: Multi-node distributed computing across multiple machines for workflow execution
# @features: Distributed workflow execution, load balancing, network-based node coordination
# @link: https://github.com/robertvoy/ComfyUI-Distributed
# @use_case: Scale workflows across multiple machines in a cluster
log_info "Installing ComfyUI-Distributed for multi-node workflow distribution..."
install_custom_node_from_git "ComfyUI-Distributed" "https://github.com/pixeloven/ComfyUI-Distributed.git"

# ComfyUI_NetDist
# @description: Network-based model distribution and caching across infrastructure
# @features: Model sharing, distributed model caching, network-based model loading
# @link: https://github.com/city96/ComfyUI_NetDist
# @use_case: Efficient model sharing and caching across network infrastructure
log_info "Installing ComfyUI_NetDist for network-based model distribution..."
install_custom_node_from_git "ComfyUI_NetDist" "https://github.com/city96/ComfyUI_NetDist.git"

