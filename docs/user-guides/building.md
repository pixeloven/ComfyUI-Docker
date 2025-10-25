# Building Images

How to build ComfyUI Docker images locally or use pre-built images from GitHub Container Registry.

## Using Pre-Built Images (Recommended)

Pre-built images are automatically published to GitHub Container Registry and used by default in docker-compose.yml.

### Available Images

| Image | Tag | Description |
|-------|-----|-------------|
| `ghcr.io/pixeloven/comfyui-docker/core` | `cuda-latest` | Essential ComfyUI with CUDA GPU support |
| `ghcr.io/pixeloven/comfyui-docker/complete` | `cuda-latest` | Full features with custom nodes |
| `ghcr.io/pixeloven/comfyui-docker/core` | `cpu-latest` | CPU-only mode |

### Pull Latest Images

```bash
# Pull all configured images
docker compose pull

# Pull specific profile
docker compose --profile complete pull
```

### Image Updates

Images are rebuilt automatically:
- **Weekly**: Every Sunday at 2:00 AM UTC with latest dependencies
- **On Release**: When new versions are tagged
- **Manual**: Via GitHub Actions workflow

### Override Image Version

Use a specific version or tag:

```bash
# Use development build
COMFY_IMAGE=ghcr.io/pixeloven/comfyui-docker/core:cuda-dev docker compose up -d

# Use specific commit tag
COMFY_IMAGE=ghcr.io/pixeloven/comfyui-docker/core:cuda-abc1234 docker compose up -d
```

## Building Locally

Build images locally for development or customization using Docker Buildx Bake.

### Build All Images

```bash
# Build complete stack
docker buildx bake all --load

# Build specific groups
docker buildx bake cuda --load        # CUDA GPU images
docker buildx bake cpu --load         # CPU-only images
docker buildx bake runtime --load     # Base runtime layers only
docker buildx bake core --load        # Core ComfyUI images
```

### Build Individual Targets

```bash
# Core images
docker buildx bake core-cuda --load
docker buildx bake core-cpu --load

# Complete image
docker buildx bake complete-cuda --load

# Runtime base images
docker buildx bake runtime-cuda --load
docker buildx bake runtime-cpu --load
```

### Build Architecture

The project uses a multi-stage build hierarchy:

```
runtime-cuda/cpu → core-cuda/cpu → complete-cuda
```

**Build Stages:**
1. **Runtime** (`services/runtime/`): Base Ubuntu + CUDA/CPU runtime
2. **Core** (`services/comfy/core/`): ComfyUI installed at `/app`
3. **Complete** (`services/comfy/complete/`): Enhanced with custom nodes

**Tip:** Build base images first for faster iteration:
```bash
docker buildx bake runtime --load
docker buildx bake core-cuda --load
# Now modify complete layer and rebuild quickly
docker buildx bake complete-cuda --load
```

### Development Builds

```bash
# Development image tag
IMAGE_LABEL=dev docker buildx bake all --load

# Clean build (bypass cache)
docker buildx bake all --load --no-cache

# Build for multiple platforms
PLATFORMS=linux/amd64,linux/arm64 docker buildx bake all --push
```

## Build Configuration

### Environment Variables

Configure builds using environment variables:

```bash
# Registry and image naming
REGISTRY_URL=ghcr.io/myuser/comfyui-docker/
IMAGE_LABEL=custom
PLATFORMS=linux/amd64

# Build with custom settings
REGISTRY_URL=myregistry.com/ IMAGE_LABEL=v1.0 docker buildx bake all --load
```

### Validate Build Configuration

```bash
# Preview build configuration
docker buildx bake --print all

# Validate docker-compose.yml
docker compose config --quiet
```

## After Building

Use your locally built images:

```bash
# Docker compose automatically uses local images if available
docker compose up -d

# Or override the image
COMFY_IMAGE=localhost/core:cuda-dev docker compose up -d
```

## Troubleshooting

### Clear Build Cache

```bash
# Remove build cache
docker buildx prune

# Remove all build cache (including unused)
docker buildx prune -a
```

### Debug Build Issues

```bash
# Build with detailed output
docker buildx bake core-cuda --load --progress=plain

# Check build logs
docker buildx bake core-cuda --load 2>&1 | tee build.log
```

### Build Fails with Cache Issues

```bash
# Force clean rebuild
docker buildx bake all --load --no-cache
```

---

**Next:** [Running Containers](running.md) | [Data Management](data.md) | [Performance Tuning](performance.md)
