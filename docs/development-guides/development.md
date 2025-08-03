# Development Guide

Complete guide for building, customizing, and contributing to ComfyUI Docker.

## Quick Development Setup

### Prerequisites
- **Docker** 24.0+ with Buildx
- **Docker Compose** 2.0+
- **Git** for version control
- **NVIDIA Docker** (for GPU development)

### Clone and Setup
```bash
git clone https://github.com/pixeloven/ComfyUI-Docker.git
cd ComfyUI-Docker

# Build base images
docker buildx bake runtime

# Build application images  
docker buildx bake base

# Test locally
docker compose up -d
```

## Architecture Overview

### Multi-Stage Build System
```
┌─────────────────┐    ┌─────────────────┐
│   runtime-cuda  │    │   runtime-cpu   │
│   (Ubuntu +     │    │   (Ubuntu       │
│    CUDA)        │    │    Base)        │
└─────────┬───────┘    └─────────┬───────┘
          │                      │
          ▼                      ▼
┌─────────────────┐    ┌─────────────────┐
│    core-cuda    │    │    core-cpu     │
│  (ComfyUI +     │    │  (ComfyUI       │
│   CUDA)         │    │   CPU-only)     │
└─────────┬───────┘    └─────────────────┘
          │
          ▼
┌─────────────────┐
│  complete-cuda  │
│ (Full Package + │
│ SageAttention)  │
└─────────────────┘
```

### Build Targets

**Runtime Layer:**
- `runtime-cpu` - Base CPU runtime (Ubuntu 24.04)
- `runtime-cuda` - Base CUDA runtime (Ubuntu 24.04 + CUDA)

**Application Layer:**
- `core-cpu` - ComfyUI with CPU-only support
- `core-cuda` - ComfyUI with CUDA support

**Extended Layer:**
- `complete-cuda` - Complete package with custom nodes and optimizations

## Building Images

### Quick Build Commands
```bash
# Build all images
docker buildx bake all

# Build specific groups
docker buildx bake cuda       # CUDA stack
docker buildx bake cpu        # CPU stack
docker buildx bake runtime    # Runtime layer only

# Build individual targets
docker buildx bake core-cpu
docker buildx bake complete-cuda
```

### Development Builds
```bash
# Build with custom tags
IMAGE_LABEL=dev docker buildx bake all

# Build without cache (clean build)
docker buildx bake all --no-cache

# Build and push to registry
docker buildx bake all --push
```

## Local Development

### Testing Changes
```bash
# Test basic functionality
docker compose up -d
curl -f http://localhost:8188/system_stats

# Test CPU mode
docker compose --profile cpu up -d

# View logs
docker compose logs -f core-cuda
```

### Development Profiles
```bash
# Development with volume mounts
docker compose -f docker-compose.dev.yml up -d

# Individual service testing
docker compose --profile core up -d
docker compose --profile complete up -d
docker compose --profile cpu up -d
```

## Customization

### Adding Custom Nodes

**Method 1: Extend Existing Image**
```dockerfile
FROM ghcr.io/pixeloven/comfyui-docker/core:cuda-latest

# Install custom nodes
RUN comfy node install ComfyUI-Custom-Node-Name

# Or install via git
RUN cd /home/comfy/ComfyUI/custom_nodes && \
    git clone https://github.com/author/custom-node.git
```

**Method 2: Build Scripts**
```bash
# Add to services/comfy/extended/scripts/
# Files in scripts/ are executed during container startup
```

### Custom Models
```bash
# Add models to data directory
mkdir -p ./data/models/checkpoints
wget -O ./data/models/checkpoints/model.safetensors https://example.com/model.safetensors
```

### Environment Customization
```bash
# Custom environment variables
export COMFY_PORT=8080
export CLI_ARGS="--lowvram --preview-method auto"

# Custom startup script
./scripts/custom-startup.sh
```

## Performance Optimization

### Build Optimization
- **Multi-stage builds** minimize final image size
- **Layer cache** reuses common layers across builds  
- **Registry cache** shares cache across developers

### Runtime Optimization
- **SageAttention** for 2-3x faster attention in complete-cuda
- **Memory-efficient** attention methods
- **GPU optimization** with proper CUDA configuration

### Development Tips
```bash
# Build incrementally
docker buildx bake runtime     # Build base first
docker buildx bake core-cuda   # Then application

# Use cache effectively
docker buildx bake all --cache-from=type=registry,ref=ghcr.io/pixeloven/comfyui-docker/runtime:cuda-cache

# Monitor build progress
docker buildx bake all --progress=plain
```

## Testing

### Unit Testing
```bash
# Test image functionality
docker run --rm ghcr.io/pixeloven/comfyui-docker/core:cuda-latest python --version

# Test GPU access
docker run --rm --gpus all ghcr.io/pixeloven/comfyui-docker/core:cuda-latest nvidia-smi
```

### Integration Testing
```bash
# Test full stack
docker compose up -d
sleep 30
curl -f http://localhost:8188/system_stats

# Test workflows
curl -X POST http://localhost:8188/prompt \
  -H "Content-Type: application/json" \
  -d @test-workflow.json
```

### Automated Testing
```bash
# Run CI tests locally
.github/scripts/test-images.sh

# Test with different configurations
CLI_ARGS="--cpu" docker compose up -d
CLI_ARGS="--lowvram" docker compose up -d
```

## Contributing

### Development Workflow
1. **Fork** the repository
2. **Create feature branch**: `git checkout -b feature/my-feature`
3. **Make changes** and test locally
4. **Build and test**: `docker buildx bake all`
5. **Submit PR** with clear description

### Code Standards
- **Dockerfile best practices**: Multi-stage, minimal layers, proper caching
- **Shell scripts**: Use bash, proper error handling, logging
- **Documentation**: Update docs for any user-facing changes
- **Testing**: Ensure all build targets work

### PR Guidelines
- **Clear description** of changes and motivation
- **Test locally** before submitting
- **Update documentation** if needed
- **Follow existing patterns** in build configuration

## Troubleshooting

### Build Issues
```bash
# Clear build cache
docker buildx prune

# Check build context
docker buildx bake --print all

# Debug specific target
docker buildx bake runtime-cuda --progress=plain
```

### Runtime Issues
```bash
# Check container logs
docker compose logs -f

# Access container for debugging
docker compose exec core-cuda bash

# Check system resources
docker stats
```

### Common Problems

**GPU not detected**
```bash
# Check NVIDIA runtime
docker run --rm --gpus all nvidia/cuda:12.0-runtime-ubuntu20.04 nvidia-smi

# Verify Docker GPU support
docker info | grep -i nvidia
```

**Build cache issues**
```bash
# Force rebuild
docker buildx bake all --no-cache

# Check cache usage
docker system df
```

**Permission issues**
```bash
# Fix file ownership
sudo chown -R $USER:$USER ./data

# Check container user
docker compose exec core-cuda id
```

## Advanced Topics

### Multi-Platform Builds
```bash
# Setup buildx for multi-platform
docker buildx create --name mybuilder --use

# Build for multiple platforms
PLATFORMS=linux/amd64,linux/arm64 docker buildx bake all --push
```

### Custom Registry
```bash
# Build for custom registry
REGISTRY_URL=myregistry.com/comfyui/ docker buildx bake all --push
```

### Development Images
```bash
# Create development variants
FROM ghcr.io/pixeloven/comfyui-docker/core:cuda-latest

# Add development tools
RUN pip install ipython jupyter black

# Mount source code
VOLUME ["/workspace"]
```

## Project Structure

```
services/
├── runtime/                    # Base runtime images
│   ├── dockerfile.cpu.runtime  # CPU runtime
│   └── dockerfile.cuda.runtime # CUDA runtime
│
└── comfy/                     # ComfyUI services
    ├── base/                  # Base ComfyUI image
    │   ├── dockerfile.comfy.base
    │   ├── startup.sh
    │   └── entrypoint.sh
    │
    └── extended/              # Extended features
        ├── dockerfile.comfy.cuda.extended
        ├── extra-requirements.txt
        └── scripts/           # Startup scripts
            ├── 00-setup-file-structure.sh
            ├── 01-setup-example-workflows.sh
            └── lib/           # Shared libraries
```

## Resources

- **[Docker Buildx Bake](https://docs.docker.com/build/bake/)** - Build configuration reference
- **[ComfyUI API](https://github.com/comfyanonymous/ComfyUI)** - ComfyUI documentation
- **[NVIDIA Container Runtime](https://github.com/NVIDIA/nvidia-container-runtime)** - GPU support

