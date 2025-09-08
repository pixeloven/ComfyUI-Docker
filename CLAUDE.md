# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ComfyUI-Docker is a production-ready Docker containerization setup for ComfyUI, providing GPU-accelerated AI image generation with multiple deployment modes. The project uses a multi-stage build architecture with Docker Buildx Bake for efficient image management.

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
2. **Core Layer** (`services/comfy/core/`): ComfyUI + GPU/CPU support
3. **Complete Layer** (`services/comfy/complete/`): Full package with custom nodes

### Service Profiles
- **Core** (`core-cuda`): Essential ComfyUI with GPU, fastest startup
- **Complete** (`complete-cuda`): Full features with SageAttention optimization
- **CPU** (`core-cpu`): CPU-only compatibility mode

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
All user data persists in `./data/`:
```
data/
├── models/      # AI models, checkpoints, LoRAs
├── input/       # Input images
├── output/      # Generated outputs
├── user/        # User configurations
└── temp/        # Temporary files
```

## Custom Node Installation

The complete image uses a sophisticated post-install system:

1. **Scripts execute in numerical order** (00-, 01-, 02-, etc.)
2. **One-time execution** using `.post_install_done` marker
3. **Colored logging** with standardized functions
4. **Git-based installation** with fuzzy matching for existing nodes

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
# Docker Compose
COMFY_PORT=8188              # Web interface port
COMFY_IMAGE=custom:latest    # Override default image
COMFY_BASE_DIRECTORY=./data  # Data directory
PUID=1000                    # User ID
PGID=1000                    # Group ID
CLI_ARGS="--lowvram"         # ComfyUI launch arguments

# Docker Bake
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