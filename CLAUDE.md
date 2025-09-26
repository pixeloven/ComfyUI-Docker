# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ComfyUI-Docker is a production-ready Docker containerization setup for ComfyUI, providing GPU-accelerated AI image generation with multiple deployment modes. The project uses a multi-stage build architecture with Docker Buildx Bake for efficient image management.

## Setup

### Data Directory Structure
Data is organized in subdirectories that mount directly to ComfyUI's default structure at `/app`. Each subdirectory is mounted individually using environment variables:

```bash
# Default usage (uses ./data subdirectories)
docker compose up -d

# Custom individual paths
COMFY_CUSTOM_NODE_PATH=/path/to/custom_nodes \
COMFY_INPUT_PATH=/path/to/input \
COMFY_MODEL_PATH=/path/to/models \
COMFY_OUTPUT_PATH=/path/to/output \
COMFY_TEMP_PATH=/path/to/temp \
COMFY_USER_PATH=/path/to/user \
docker compose up -d

# Custom ownership (if different from current user)
PUID=1001 PGID=1001 docker compose up -d
```

**Required Data Structure:**
```
data/
├── models/          → /app/models (AI models, checkpoints)
├── custom_nodes/    → /app/custom_nodes (extensions)
├── input/          → /app/input (input images/workflows)
├── output/         → /app/output (generated content)
├── temp/           → /app/temp (temporary files)
└── user/           → /app/user (user configs)
```

## Build Commands

### Docker Bake (Primary Build System)
```bash
# Build all images
docker buildx bake all

# Build specific target groups
docker buildx bake cuda         # CUDA GPU stack
docker buildx bake cpu          # CPU-only stack  
docker buildx bake runtime      # Base runtime layers only
docker buildx bake core         # Core ComfyUI images

# Build individual targets
docker buildx bake core-cuda
docker buildx bake core-cpu
docker buildx bake complete-cuda
docker buildx bake runtime-cuda
docker buildx bake runtime-cpu

# Development builds
IMAGE_LABEL=dev docker buildx bake all
docker buildx bake all --no-cache        # Clean build
docker buildx bake all --push            # Build and push to registry
```

### Docker Compose (Deployment)
```bash
# Core mode (default, recommended)
docker compose up -d
docker compose --profile core up -d

# Complete mode (all features)
docker compose --profile complete up -d

# CPU-only mode
docker compose --profile cpu up -d

# Validate configuration
docker compose config --quiet
```

## Architecture

### Multi-Stage Build Hierarchy
```
runtime-cuda/cpu → core-cuda/cpu → complete-cuda
```

**Build Stages:**
1. **Runtime Layer** (`services/runtime/`): Base Ubuntu + CUDA/CPU runtime
2. **Core Layer** (`services/comfy/core/`): ComfyUI installed at `/app`
3. **Complete Layer** (`services/comfy/complete/`): Enhanced with custom nodes and optimizations

### Service Profiles
- **Core** (`core-cuda`): Essential ComfyUI at `/app`, direct volume mounting
- **Complete** (`complete-cuda`): Full features with post-install automation
- **CPU** (`core-cpu`): CPU-only mode with same `/app` structure

## Directory Structure

```
services/
├── runtime/                    # Base runtime images
│   ├── dockerfile.cuda.runtime # CUDA runtime (Ubuntu + CUDA)
│   └── dockerfile.cpu.runtime  # CPU runtime (Ubuntu base)
└── comfy/                     
    ├── core/                   # Core ComfyUI
    │   ├── dockerfile.comfy.core
    │   ├── startup.sh          # Simple startup script
    │   └── entrypoint.sh
    └── complete/               # Extended features
        ├── dockerfile.comfy.cuda.complete
        ├── startup.sh          # Advanced startup with post-install
        ├── extra-requirements.txt
        └── scripts/            # Numbered post-install scripts
            ├── 00-setup-file-structure.sh
            ├── 01-setup-example-workflows.sh
            ├── 02-install-platform-essentials.sh
            └── lib/            # Shared libraries
                ├── logging.sh  # Colored logging functions
                └── custom-nodes.sh # Node installation utilities
```

### Data Persistence
Individual subdirectory mounting to ComfyUI's default structure at `/app`:
```
Host: ./data/           Container: /app/
├── models/         →  /app/models/      (AI models, checkpoints, LoRAs)
├── custom_nodes/   →  /app/custom_nodes/ (Extensions and plugins)
├── input/          →  /app/input/       (Input images and workflows)
├── output/         →  /app/output/      (Generated outputs)
├── temp/           →  /app/temp/        (Temporary files)
└── user/           →  /app/user/        (User configurations)
```

Each subdirectory is mounted using individual environment variables:
- `COMFY_CUSTOM_NODE_PATH` → `/app/custom_nodes`
- `COMFY_INPUT_PATH` → `/app/input`
- `COMFY_MODEL_PATH` → `/app/models`
- `COMFY_OUTPUT_PATH` → `/app/output`
- `COMFY_TEMP_PATH` → `/app/temp`
- `COMFY_USER_PATH` → `/app/user`

**Benefits:**
- ✅ Granular control over each data directory
- ✅ Standard Docker app structure at `/app`
- ✅ Direct alignment with ComfyUI defaults
- ✅ Flexible path customization

## Custom Node Installation

The complete image uses a sophisticated post-install system with 9 numbered scripts:

**Available Scripts:**
- `00-setup-file-structure.sh` - Initialize directory structure
- `01-setup-example-workflows.sh` - Install example workflows
- `02-install-platform-essentials.sh` - Core platform tools
- `03-install-workflow-enhancers.sh` - Workflow enhancement nodes
- `04-install-detection-segmentation.sh` - Detection/segmentation tools
- `05-install-image-enhancers.sh` - Image processing nodes
- `06-install-control-systems.sh` - Control system nodes
- `07-install-video-animation.sh` - Video/animation tools
- `08-install-distribution-systems.sh` - Distribution system nodes

**System Features:**
1. **Scripts execute in numerical order** (00-08)
2. **One-time execution** using `.post_install_done` marker
3. **Colored logging** with standardized functions via `lib/logging.sh`
4. **Git-based installation** with fuzzy matching via `lib/custom-nodes.sh`

**Library Functions:**
- `lib/logging.sh`: Provides `log_info()`, `log_success()`, `log_warning()`, `log_error()`
- `lib/custom-nodes.sh`: Provides `install_custom_node_from_git()` with fuzzy matching

### Adding Custom Nodes
Create numbered scripts in `services/comfy/complete/scripts/`:
```bash
#!/bin/bash
set -e
source "$(dirname "$0")/lib/logging.sh"
source "$(dirname "$0")/lib/custom-nodes.sh"

log_info "Installing my custom nodes..."
install_custom_node_from_git "NodeName" "https://github.com/author/repo.git"
log_success "Installation completed"
```

## Environment Variables

```bash
# Docker Compose - Server & Setup Configuration
PUID=1000                               # User ID for container ownership
PGID=1000                               # Group ID for container ownership
COMFY_PORT=8188                         # Web interface port

# Docker Compose - Individual Path Configuration
COMFY_CUSTOM_NODE_PATH=./data/custom_nodes  # Custom nodes directory
COMFY_INPUT_PATH=./data/input               # Input images/workflows
COMFY_MODEL_PATH=./data/models              # AI models, checkpoints
COMFY_OUTPUT_PATH=./data/output             # Generated content
COMFY_TEMP_PATH=./data/temp                 # Temporary files
COMFY_USER_PATH=./data/user                 # User configurations

# Docker Compose - Optional Overrides
COMFY_IMAGE=custom:latest               # Override default image
CLI_ARGS="--lowvram"                   # ComfyUI launch arguments

# Docker Bake - Build Configuration
REGISTRY_URL=ghcr.io/pixeloven/comfyui-docker/
IMAGE_LABEL=latest
PLATFORMS=linux/amd64,linux/arm64
```

## Testing Commands

```bash
# Configuration validation
docker compose config --quiet
docker buildx bake --print all

# Service functionality
curl -f http://localhost:8188/system_stats

# GPU testing
docker run --rm --gpus all IMAGE nvidia-smi

# Profile testing
docker compose --profile cpu config --services | grep -q core-cpu
```

## Common Development Tasks

### Local Development
```bash
# Build base images first for faster iteration
docker buildx bake runtime
docker buildx bake core-cuda

# Test changes
docker compose up -d
docker compose logs -f core-cuda
```

### Adding New Build Targets
1. Add target to `docker-bake.hcl`
2. Update CI validation in `.github/workflows/ci.yml`
3. Test with `docker buildx bake --print TARGET`

### Troubleshooting
```bash
# Clear build cache
docker buildx prune

# Debug builds  
docker buildx bake TARGET --progress=plain

# Container debugging
docker compose exec core-cuda bash
```

## CI/CD Integration

The project uses GitHub Actions for validation and automated builds:
- **Configuration validation** for docker-compose.yml and docker-bake.hcl
- **Profile testing** to ensure service configurations
- **Multi-target builds** with registry caching
- **Automatic deployment** on main branch pushes

Build artifacts are pushed to GitHub Container Registry at:
`ghcr.io/pixeloven/comfyui-docker/`