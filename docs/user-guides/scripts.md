# Scripts Guide

Complete guide to the custom node installation scripts in ComfyUI Docker's **Complete** mode.

## Overview

The **Complete** profile includes a post-install script system that automatically installs 13+ custom nodes on first container startup. This guide explains how the system works and how to modify it.

**Note:** Scripts are only used in **Complete mode**. The **Core** and **CPU** modes do not use scripts.

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
4. Subsequent startups skip script execution

### Script Location

Scripts are located in `services/comfy/complete/scripts/`:

```
services/comfy/complete/scripts/
├── lib/
│   ├── logging.sh              # Colored logging functions
│   └── custom-nodes.sh         # Node installation utilities
├── 00-setup-file-structure.sh  # Initialize directories
├── 01-setup-example-workflows.sh # Install example workflows
├── 02-install-platform-essentials.sh # Core platform tools
├── 03-install-workflow-enhancers.sh # Workflow enhancement nodes
├── 04-install-detection-segmentation.sh # Detection/segmentation
├── 05-install-image-enhancers.sh # Image processing nodes
├── 06-install-control-systems.sh # Control system nodes
├── 07-install-video-animation.sh # Video/animation tools
└── 08-install-distribution-systems.sh # Distribution systems
```

## Installed Custom Nodes

The Complete mode pre-installs these custom nodes:

### Platform Essentials (Script 02)
- **ComfyUI-Custom-Scripts** - Essential UI improvements and utilities

### Workflow Enhancers (Script 03)
- **rgthree-comfy** - Workflow utilities and quality of life improvements
- **ComfyUI-KJNodes** - Additional utility nodes
- **ComfyUI-TeaCache** - Caching for faster workflow execution
- **ComfyUI-Inspire-Pack** - Workflow inspiration and tools

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

### Adding New Custom Nodes

To add custom nodes to the installation:

1. **Edit the appropriate script** (or create a new one):
   ```bash
   vim services/comfy/complete/scripts/03-install-workflow-enhancers.sh
   ```

2. **Add your node using the helper function**:
   ```bash
   #!/bin/bash
   set -e
   source "$(dirname "$0")/lib/logging.sh"
   source "$(dirname "$0")/lib/custom-nodes.sh"

   log_info "Installing workflow enhancers..."

   install_custom_node_from_git "MyCustomNode" "https://github.com/author/repo.git"

   log_success "Workflow enhancers installed"
   ```

3. **Rebuild the Complete image**:
   ```bash
   docker buildx bake complete-cuda --load
   ```

### Creating New Scripts

To add a new script category:

1. **Create numbered script** (09-19 available):
   ```bash
   cat > services/comfy/complete/scripts/09-my-custom-setup.sh << 'SCRIPT'
   #!/bin/bash
   set -e
   source "$(dirname "$0")/lib/logging.sh"
   source "$(dirname "$0")/lib/custom-nodes.sh"

   log_info "Installing my custom components..."

   # Install custom nodes
   install_custom_node_from_git "NodeName" "https://github.com/author/node.git"

   # Install Python packages
   pip install my-package

   log_success "Custom components installed"
   SCRIPT
   ```

2. **Make it executable**:
   ```bash
   chmod +x services/comfy/complete/scripts/09-my-custom-setup.sh
   ```

3. **Rebuild the image**:
   ```bash
   docker buildx bake complete-cuda --load
   ```

## Logging Functions

Scripts use standardized logging from `lib/logging.sh`:

```bash
source "$(dirname "$0")/lib/logging.sh"

log_info "Information message"      # Blue [INFO]
log_success "Success message"       # Green [SUCCESS]
log_warning "Warning message"       # Yellow [WARNING]
log_error "Error message"           # Red [ERROR]
```

## Custom Node Helper

The `lib/custom-nodes.sh` library provides:

```bash
source "$(dirname "$0")/lib/custom-nodes.sh"

# Install a custom node from git with fuzzy matching
install_custom_node_from_git "NodeName" "https://github.com/author/repo.git"
```

**Features:**
- Clones the repository to `/app/custom_nodes/`
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

## Viewing Installation Logs

```bash
# View all logs
docker compose logs complete-cuda

# Follow logs in real-time
docker compose logs -f complete-cuda

# Search for specific node
docker compose logs complete-cuda | grep "NodeName"

# Check for errors
docker compose logs complete-cuda | grep ERROR
```

## Troubleshooting

### Scripts Not Running

**Check for marker file:**
```bash
docker compose exec complete-cuda ls -la | grep post_install
```

If `.post_install_done` exists, scripts won't run. Remove it to force execution.

### Script Execution Errors

**View detailed logs:**
```bash
docker compose logs complete-cuda | grep -A 10 ERROR
```

**Test individual script:**
```bash
docker compose exec complete-cuda bash /app/scripts/03-install-workflow-enhancers.sh
```

### Custom Node Installation Fails

**Check node exists:**
```bash
docker compose exec complete-cuda ls -la /app/custom_nodes/
```

**Verify git URL is accessible:**
```bash
git ls-remote https://github.com/author/repo.git
```

**Check Python dependencies:**
```bash
docker compose exec complete-cuda pip list | grep package-name
```

## Migration to Snapshot System

**Note:** This project is planning to migrate from runtime scripts to a snapshot-based installation system. See [Custom Nodes Migration Plan](../project-management/custom-nodes-migration.md) for details.

The new approach will:
- Install custom nodes at build time instead of runtime
- Use ComfyUI's native snapshot format
- Eliminate the need for custom bash scripts
- Provide faster container startup

---

**[⬆ Back to Documentation](../index.md)** | **[🚀 Quick Start](quick-start.md)** | **[⚙️ Configuration](configuration.md)**
