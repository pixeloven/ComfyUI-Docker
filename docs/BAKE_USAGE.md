# Docker Bake Usage Guide

This guide explains how to use the Docker Bake configuration for building ComfyUI-Docker images with different runtimes.

## Quick Start

### Build NVIDIA Runtime (Default)
```bash
docker buildx bake
```

### Build CPU Runtime
```bash
docker buildx bake --set "*.args.RUNTIME=cpu"
```

### Build All Images
```bash
docker buildx bake all
```

## Available Targets

### Runtime Images
- `runtime-nvidia` - Base NVIDIA CUDA runtime
- `runtime-cpu` - Base CPU runtime

### Application Images
- `comfy-nvidia` - ComfyUI with NVIDIA support
- `comfy-cpu` - ComfyUI with CPU-only support
- `comfy-setup` - Setup utility image

### Convenience Groups
- `all` - Build all images
- `nvidia` - Build NVIDIA runtime and application
- `cpu` - Build CPU runtime and application
- `dev` - Build development images (no caching)

## Build Commands

### Build Specific Target
```bash
# Build only NVIDIA ComfyUI
docker buildx bake comfy-nvidia

# Build only CPU ComfyUI
docker buildx bake comfy-cpu

# Build setup utility
docker buildx bake comfy-setup
```

### Build with Custom Registry
```bash
docker buildx bake --set "*.args.REGISTRY_URL=myregistry.com/myuser"
```

### Build for Multiple Platforms
```bash
docker buildx bake --set "*.platforms=linux/amd64,linux/arm64"
```

### Build Development Images
```bash
# Build dev images without caching (faster iteration)
docker buildx bake dev
```

## Variables

You can customize the build by setting these variables:

- `REGISTRY_URL` - Container registry URL (default: `ghcr.io/pixeloven`)
- `IMAGE_LABEL` - Image tag label (default: `latest`)
- `RUNTIME` - Runtime type: `nvidia` or `cpu` (default: `nvidia`)
- `PLATFORMS` - Target platforms (default: `["linux/amd64"]`)

## Examples

### Local Development
```bash
# Build CPU version for local testing
docker buildx bake comfy-cpu --set "*.tags=comfyui:local"
```

### Production Build
```bash
# Build all images for production
docker buildx bake all --set "*.args.IMAGE_LABEL=v1.0.0"
```

### Custom Registry
```bash
# Build for your own registry
docker buildx bake all \
  --set "*.args.REGISTRY_URL=myregistry.com/myuser" \
  --set "*.args.IMAGE_LABEL=latest"
```

## Caching

The bake configuration includes registry-based caching for faster builds:

- Cache layers are stored in the registry
- Subsequent builds will reuse cached layers
- Development builds (`dev` group) skip caching for faster iteration

## Troubleshooting

### Clear Cache
```bash
# Remove all build cache
docker buildx prune -a
```

### Build with No Cache
```bash
# Force rebuild without cache
docker buildx bake --no-cache
```

### Debug Build
```bash
# Build with verbose output
docker buildx bake --progress=plain
``` 