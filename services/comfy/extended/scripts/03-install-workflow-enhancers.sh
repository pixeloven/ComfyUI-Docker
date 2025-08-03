#!/bin/bash
set -e

# Source logging functions
source "$(dirname "$0")/lib/logging.sh"

# Source custom nodes installation functions
source "$(dirname "$0")/lib/custom-nodes.sh"

log_info "Starting workflow enhancers installation..."

# rgthree-comfy
# @description: Advanced workflow organization, routing, and debugging nodes with powerful features for complex workflow management
# @link: https://github.com/rgthree/rgthree-comfy
install_custom_node "rgthree-comfy" "rgthree-comfy"

# ComfyUI-KJNodes
# @description: Utility nodes for flow control, debugging, and workflow enhancement with various helper nodes
# @link: https://github.com/kijai/ComfyUI-KJNodes
install_custom_node "ComfyUI-KJNodes" "ComfyUI-KJNodes"

# ComfyUI-TeaCache
# @description: Performance optimization through intelligent caching to speed up workflow execution
# @link: https://github.com/welltop-cn/ComfyUI-TeaCache
install_custom_node "ComfyUI-TeaCache" "comfyui-teacache"

# ComfyUI-Inspire-Pack
# @description: Creative workflow enhancements and artistic tools for inspiration and experimentation
# @link: https://github.com/ltdrdata/ComfyUI-Inspire-Pack
install_custom_node "ComfyUI-Inspire-Pack" "ComfyUI-Inspire-Pack"

log_success "Workflow enhancers installation completed successfully" 