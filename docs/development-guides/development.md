# Development

Development setup and contributing to ComfyUI Docker.

## Setup

```bash
# Clone and setup
git clone https://github.com/pixeloven/ComfyUI-Docker.git
cd ComfyUI-Docker

# Create .env file with default settings
cat > .env << EOF
# User/Group IDs for container permissions
PUID=1000
PGID=1000

# ComfyUI Configuration
COMFY_PORT=8188
CLI_ARGS=

# Performance Configuration
CLI_ARGS=
EOF
```

## Environment Variables

The application supports the following environment variables:

### User Configuration
- `PUID` (default: 1000) - User ID for container permissions
- `PGID` (default: 1000) - Group ID for container permissions

### ComfyUI Configuration
- `COMFY_PORT` (default: 8188) - Port for ComfyUI web interface
- `CLI_ARGS` (default: "") - Additional CLI arguments for ComfyUI
  - `--cpu` - Force CPU-only mode
  - `--lowvram` - Low VRAM mode for 4-6GB GPUs
  - `--novram` - No VRAM mode

### Performance Configuration
- `CLI_ARGS` (default: "") - Additional CLI arguments for ComfyUI performance tuning

### Build Configuration
- `REGISTRY_URL` (default: "ghcr.io/pixeloven/comfyui-docker/") - Docker registry URL
- `IMAGE_LABEL` (default: "latest") - Image tag
- `RUNTIME` (default: "nvidia") - Runtime type
- `PLATFORMS` (default: ["linux/amd64"]) - Target platforms

## Building Images

This project uses Docker Bake for building images with support for multiple runtimes and efficient caching.

### Prerequisites

```bash
# Ensure Docker Buildx is available
docker buildx version

# Create a new builder instance if needed
docker buildx create --name mybuilder --use
```

### Quick Build Commands

```bash
# Build all images (NVIDIA and CPU runtimes)
docker buildx bake all

# Build only NVIDIA runtime and application
docker buildx bake nvidia

# Build only CPU runtime and application
docker buildx bake cpu

# Build specific target
docker buildx bake comfy-nvidia
docker buildx bake comfy-cpu
```

### Available Targets

#### Runtime Images
- `runtime-nvidia` - Base NVIDIA CUDA runtime with cuDNN
- `runtime-cpu` - Base CPU runtime (Ubuntu 24.04)

#### Application Images
- `comfy-nvidia` - ComfyUI with NVIDIA GPU support
- `comfy-cpu` - ComfyUI with CPU-only support

#### Convenience Groups
- `all` - Build all images (runtimes + applications)
- `runtime` - Build both runtime base images
- `comfy` - Build both ComfyUI application images
- `nvidia` - Build NVIDIA runtime and application
- `cpu` - Build CPU runtime and application

### Custom Build Options

```bash
# Build with custom registry
docker buildx bake all --set "*.args.REGISTRY_URL=myregistry.com/myuser"

# Build with custom image label
docker buildx bake all --set "*.args.IMAGE_LABEL=v1.0.0"

# Build for multiple platforms
docker buildx bake all --set "*.platforms=linux/amd64,linux/arm64"

# Build without cache (force rebuild)
docker buildx bake all --no-cache

# Build with verbose output
docker buildx bake all --progress=plain
```

### Troubleshooting Builds

```bash
# Check build context
docker buildx bake --print

# Debug specific target
docker buildx bake comfy-nvidia --progress=plain

# Clear build cache
docker buildx prune -a

# Check available builders
docker buildx ls
```

## Test Workflow

```bash
# Start development environment
docker compose --profile comfy-nvidia up -d

# Monitor logs
docker compose logs -f

# Test changes
docker compose restart
```

## Testing

### Local Testing
```bash
# Test GPU service
docker compose --profile comfy-nvidia up -d
curl -f http://localhost:8188

# Test CPU service
docker compose down
docker compose --profile comfy-cpu up -d
curl -f http://localhost:8188
```

## Contributing

### Before Contributing
1. Create a discussion describing the problem and solution
2. Fork the repository and create a feature branch
3. Test your changes locally
4. Open a pull request

### Guidelines
- Follow existing code style and patterns
- Update documentation if needed
- Keep commits focused and descriptive

## Script Development

ComfyUI Docker uses a modular script system for container bootstrapping and setup. Scripts are mounted as volumes and executed during container startup with sophisticated logging and error handling.

### Overview

- **Architecture**: Scripts stored in `scripts/category/` and mounted as volumes
- **Execution**: Automatic execution during startup with colored logging
- **Logging**: Shared logging library (`scripts/logging.sh`) for consistent output
- **Integration**: Volume mounting allows script modification without rebuilding images

### Development Resources

For comprehensive script development information, see:

**[📜 Scripts Guide](../user-guides/scripts.md)** - Complete documentation including:
- Script system architecture and execution flow
- Logging functions and colored output
- Script templates and development guidelines  
- Testing procedures and debugging techniques
- Common use cases and practical examples

### Core Development Files

Key files for script system development:

- **`services/comfy/base/startup.sh`** - Main startup script with execution logic
- **`scripts/logging.sh`** - Shared logging library for colored output
- **`scripts/base/`** - Core functionality scripts
- **`scripts/extended/`** - Extended functionality scripts

### Quick Development Test

```bash
# Test startup script syntax
bash -n services/comfy/base/startup.sh

# Build and test changes
docker buildx bake comfy-cuda
docker compose up -d && docker compose logs -f
```

