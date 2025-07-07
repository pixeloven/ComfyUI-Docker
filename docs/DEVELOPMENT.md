# Development

Development setup and contributing to ComfyUI Docker.

## Setup

```bash
# Clone and setup
git clone https://github.com/pixeloven/ComfyUI-Docker.git
cd ComfyUI-Docker
cp .env.example .env
```

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
docker buildx bake comfy-setup
```

### Available Targets

#### Runtime Images
- `runtime-nvidia` - Base NVIDIA CUDA runtime with cuDNN
- `runtime-cpu` - Base CPU runtime (Ubuntu 24.04)

#### Application Images
- `comfy-nvidia` - ComfyUI with NVIDIA GPU support
- `comfy-cpu` - ComfyUI with CPU-only support
- `comfy-setup` - Setup utility for model downloads

#### Convenience Groups
- `all` - Build all images (runtimes + applications + setup)
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
docker compose --profile comfy up -d

# Monitor logs
docker compose logs -f

# Test changes
docker compose restart
```

## Testing

### Local Testing
```bash
# Test GPU service
docker compose --profile comfy up -d
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

