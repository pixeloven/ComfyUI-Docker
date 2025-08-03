# CI/CD Guide

Docker Bake workflows and automated testing for ComfyUI Docker.

## Docker Bake Overview

This project uses [Docker Buildx Bake](https://docs.docker.com/build/bake/) for efficient multi-image builds with proper dependency management and caching.

### Build Targets

| Target | Description |
|--------|-------------|
| `runtime-cuda` | CUDA runtime base (Ubuntu 24.04 + CUDA) |
| `runtime-cpu` | CPU runtime base (Ubuntu 24.04) |  
| `core-cuda` | ComfyUI with CUDA support |
| `core-cpu` | ComfyUI with CPU-only support |
| `complete-cuda` | Complete package with custom nodes and SageAttention |

### Build Groups

| Group | Targets | Description |
|-------|---------|-------------|
| `all` | All images (runtime-cuda, runtime-cpu, core-cuda, core-cpu, complete-cuda) |
| `base` | Base images only (runtime-cuda, runtime-cpu, core-cuda, core-cpu) |
| `runtime` | Runtime images (runtime-cuda, runtime-cpu) |
| `cuda` | CUDA images (runtime-cuda, core-cuda, complete-cuda) |
| `cpu` | CPU images (runtime-cpu, core-cpu) |

## Local Development

### Quick Build Commands
```bash
# Build all images
docker buildx bake all

# Build specific groups
docker buildx bake cuda          # All CUDA images
docker buildx bake cpu           # All CPU images  
docker buildx bake runtime       # Runtime images only

# Build individual targets
docker buildx bake runtime-cuda
docker buildx bake core-cuda
docker buildx bake complete-cuda
```

### Build Configuration

The `docker-bake.hcl` file defines:
- **Multi-stage builds** with proper dependency chains
- **Registry caching** for faster subsequent builds
- **Platform targeting** (currently linux/amd64)
- **Flexible tagging** with runtime in tag names

### Development Workflow

1. **Local Testing**
   ```bash
   # Build and test locally
   docker buildx bake runtime-cuda core-cuda
   docker compose up -d
   ```

2. **Registry Push** (after validation)
   ```bash
   # Build and push to registry
   docker buildx bake all --push
   ```

## Cache Strategy

### Multi-Level Caching
- **Registry cache**: Shared across builds using `type=registry`
- **Inline cache**: Embedded in images using `type=inline`
- **Dependency cache**: Each image caches from its dependencies

### Cache Configuration
```hcl
# Example from docker-bake.hcl
cache-from = [
    "type=registry,ref=${REGISTRY_URL}runtime:cuda-cache",
    "type=registry,ref=${REGISTRY_URL}core:cuda-cache"
]
cache-to = ["type=inline"]
```

## GitHub Actions Integration

### Automated Builds
The CI pipeline automatically:
1. **Builds all images** on main branch changes
2. **Runs validation tests** to ensure images work
3. **Pushes to GitHub Container Registry** on success
4. **Updates cache** for faster subsequent builds

### Manual Triggers
```bash
# Trigger manual build
gh workflow run ci.yml
```

## Local Testing

### Build Validation
```bash
# Test specific build target
docker buildx bake --file docker-bake.hcl --print runtime-cpu

# Validate all targets exist
docker buildx bake --file docker-bake.hcl --print | grep -q "core-cpu"
docker buildx bake --file docker-bake.hcl --print | grep -q "core-cuda"
docker buildx bake --file docker-bake.hcl --print | grep -q "runtime-cpu"
docker buildx bake --file docker-bake.hcl --print | grep -q "runtime-cuda"
docker buildx bake --file docker-bake.hcl --print | grep -q "complete-cuda"
```

### Runtime Testing
```bash
# Test GPU functionality
docker compose up -d
curl -f http://localhost:8188/system_stats

# Test CPU functionality  
docker compose --profile cpu up -d
curl -f http://localhost:8188/system_stats
```

## Performance Optimization

### Build Performance
- **Parallel builds**: Dependencies build concurrently where possible
- **Registry caching**: Reuses layers across builds and machines
- **Multi-stage optimization**: Minimizes final image size

### Runtime Performance
- **SageAttention**: complete-cuda includes optimized attention computation
- **GPU optimization**: Proper CUDA runtime configuration
- **Memory efficiency**: Optimized for various VRAM configurations

## Troubleshooting

### Common Build Issues

**Cache miss problems**
```bash
# Clear build cache
docker buildx prune

# Rebuild without cache
docker buildx bake all --no-cache
```

**Registry authentication**
```bash
# Login to GitHub Container Registry
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin
```

**Dependency issues**
```bash
# Build dependencies first
docker buildx bake runtime
docker buildx bake base
docker buildx bake all
```

### Development Tips

1. **Incremental builds**: Build dependencies first for faster iteration
2. **Local testing**: Always test locally before pushing
3. **Cache warming**: Use `--push` to warm cache for team members
4. **Target isolation**: Test individual targets to isolate issues

### Build Monitoring
```bash
# Monitor build progress
docker buildx bake all --progress=plain

# Check build cache usage
docker system df
docker buildx du
```

## Advanced Usage

### Custom Registry
```bash
# Override registry
REGISTRY_URL=my-registry.com/comfyui/ docker buildx bake all --push
```

### Platform Targeting
```bash
# Multi-platform builds (requires setup)
PLATFORMS=linux/amd64,linux/arm64 docker buildx bake all --push
```

### Development Images
```bash
# Build with custom tags
IMAGE_LABEL=dev docker buildx bake all
```
