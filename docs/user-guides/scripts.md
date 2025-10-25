# Scripts Guide

Understanding the custom node installation script system in Complete mode.

## Overview

The **Complete** profile uses a post-install script system that automatically installs 13+ custom nodes on first container startup.

**Note:** Scripts are only used in **Complete mode**. Core and CPU modes do not use scripts.

## How It Works

### Automatic Installation

When you start Complete mode for the first time:

```bash
docker compose --profile complete up -d
```

The container:
1. Checks for `.post_install_done` marker file
2. If not found, executes scripts in numerical order (00-08)
3. Creates `.post_install_done` marker to prevent re-execution
4. Subsequent startups skip script execution (fast startup)

### Script Location

Scripts are located in `services/comfy/complete/scripts/`:

```
services/comfy/complete/scripts/
├── lib/
│   ├── logging.sh              # Colored logging functions
│   └── custom-nodes.sh         # Node installation utilities
├── 00-setup-file-structure.sh
├── 01-setup-example-workflows.sh
├── 02-install-platform-essentials.sh
├── 03-install-workflow-enhancers.sh
├── 04-install-detection-segmentation.sh
├── 05-install-image-enhancers.sh
├── 06-install-control-systems.sh
├── 07-install-video-animation.sh
└── 08-install-distribution-systems.sh
```

## Installed Custom Nodes

### Platform Essentials (Script 02)
- **ComfyUI-Custom-Scripts** - Essential UI improvements and utilities

### Workflow Enhancers (Script 03)
- **rgthree-comfy** - Workflow utilities and QOL improvements
- **ComfyUI-KJNodes** - Additional utility nodes
- **ComfyUI-TeaCache** - Caching for faster workflows
- **ComfyUI-Inspire-Pack** - Workflow tools

### Detection & Segmentation (Script 04)
- **ComfyUI-Impact-Pack** - Advanced detection and segmentation
- **ComfyUI-Impact-Subpack** - Additional Impact Pack components

### Image Enhancers (Script 05)
- **ComfyUI_UltimateSDUpscale** - Advanced upscaling
- **ComfyUI-RMBG** - Background removal
- **ComfyUI-IC-Light** - Lighting control

### Control Systems (Script 06)
- **ComfyUI_IPAdapter_plus** - IP-Adapter integration
- **comfyui_controlnet_aux** - ControlNet preprocessing

### Distribution Systems (Script 08)
- **ComfyUI_NetDist** - Distributed computing support

## Customizing Scripts

### Adding Custom Nodes

To add custom nodes to an existing script:

1. **Edit the script** (e.g., `services/comfy/complete/scripts/03-install-workflow-enhancers.sh`):

```bash
#!/bin/bash
set -e
source "$(dirname "$0")/lib/logging.sh"
source "$(dirname "$0")/lib/custom-nodes.sh"

log_info "Installing workflow enhancers..."

# Add your custom node
install_custom_node_from_git "MyCustomNode" "https://github.com/author/repo.git"

log_success "Workflow enhancers installed"
```

2. **Rebuild the Complete image**:

```bash
docker buildx bake complete-cuda --load
docker compose up -d
```

See [Building Images](building.md) for build details.

### Creating New Scripts

To add a new script category:

1. **Create numbered script** (09-19 available):

```bash
#!/bin/bash
set -e
source "$(dirname "$0")/lib/logging.sh"
source "$(dirname "$0")/lib/custom-nodes.sh"

log_info "Installing my custom components..."

# Install custom nodes
install_custom_node_from_git "NodeName" "https://github.com/author/node.git"

# Install Python packages if needed
pip install my-package

log_success "Custom components installed"
```

2. **Make it executable**:

```bash
chmod +x services/comfy/complete/scripts/09-my-custom-setup.sh
```

3. **Rebuild the image** (see [Building Images](building.md))

## Script Libraries

### Logging Functions

Scripts use standardized logging from `lib/logging.sh`:

```bash
source "$(dirname "$0")/lib/logging.sh"

log_info "Information message"      # Blue [INFO]
log_success "Success message"       # Green [SUCCESS]
log_warning "Warning message"       # Yellow [WARNING]
log_error "Error message"           # Red [ERROR]
```

### Custom Node Helper

The `lib/custom-nodes.sh` library provides:

```bash
source "$(dirname "$0")/lib/custom-nodes.sh"

# Install a custom node from git with fuzzy matching
install_custom_node_from_git "NodeName" "https://github.com/author/repo.git"
```

**Features:**
- Clones repository to `/app/custom_nodes/`
- Installs Python dependencies from `requirements.txt` if present
- Provides fuzzy name matching
- Handles errors gracefully

## Force Script Re-execution

To force scripts to run again:

```bash
# Remove the marker file
docker compose exec complete-cuda rm -f .post_install_done

# Restart the container
docker compose restart complete-cuda

# Watch the logs
docker compose logs -f complete-cuda
```

See [Running Containers](running.md) for Docker Compose operations.

## Viewing Installation Logs

```bash
# View all logs
docker compose logs complete-cuda

# Follow logs in real-time
docker compose logs -f complete-cuda

# Search for specific node
docker compose logs complete-cuda | grep "NodeName"
```

## Migration to Snapshot System

**Note:** This project is planning to migrate from runtime scripts to a snapshot-based installation system. See [Custom Nodes Migration Plan](../project-management/custom-nodes-migration.md) for details.

The new approach will:
- Install custom nodes at build time instead of runtime
- Use ComfyUI's native snapshot format
- Eliminate custom bash scripts
- Provide faster container startup

---

**See Also:**
- [Building Images](building.md) - Rebuild images with custom scripts
- [Running Containers](running.md) - Docker Compose operations
- [Data Management](data.md) - Custom nodes directory structure
