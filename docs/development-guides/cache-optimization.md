# Docker Build Cache Optimization

This document outlines the cache optimization strategies implemented in the ComfyUI-Docker project to significantly reduce build times and improve CI/CD efficiency.

## 🎯 Overview

Our cache optimization strategy uses multiple layers of caching to maximize build efficiency:

1. **GitHub Actions Cache** - Primary cache for CI/CD builds
2. **Registry Cache** - Persistent cache across builds
3. **Layer Optimization** - Strategic layer ordering for maximum cache hits
4. **BuildKit Features** - Advanced caching capabilities

## 🏗️ Cache Architecture

### Cache Layers

```
┌─────────────────────────────────────┐
│           GitHub Actions            │
│         (Primary Cache)             │
├─────────────────────────────────────┤
│         Registry Cache              │
│      (Persistent Cache)             │
├─────────────────────────────────────┤
│         Inline Cache                │
│      (Immediate Reuse)              │
└─────────────────────────────────────┘
```

### Build Targets and Dependencies

```
runtime-cuda ──┐
               ├── core-cuda ──┐
runtime-cpu ───┤               ├── complete-cuda
               └── core-cpu
sageattention-builder ──────────┘
```

## 🚀 Optimization Strategies

### 1. Layer Optimization

The Dockerfiles are structured to maximize cache hits:

#### Core Dockerfile Layers (Most to Least Frequent Changes)

1. **Base Runtime** - Rarely changes (Ubuntu + CUDA base)
2. **Python Environment** - Rarely changes (venv setup)
3. **comfy-cli Installation** - Rarely changes (CLI tool)
4. **ComfyUI Installation** - Changes with ComfyUI updates
5. **Application Code** - Changes with every commit
6. **Final Setup** - Rarely changes (permissions, env vars)

### 2. Cache Configuration

#### Docker Bake Variables

```hcl
variable "CACHE_TYPE" {
    default = "gha"  // gha, registry, or inline
}

variable "CACHE_MODE" {
    default = "max"  // max or min
}
```

#### Cache Sources (Priority Order)

1. **GitHub Actions Cache** - Fastest, scoped per target (CI/CD only)
2. **Inline Cache** - Immediate reuse within build (works everywhere)
3. **Registry Cache** - Persistent across builds (requires containerd driver)

### 3. Build Arguments

```hcl
args = {
    BUILDKIT_INLINE_CACHE = "1"
    DOCKER_BUILDKIT = "1"
}
```

## 📊 Expected Performance Improvements

### Build Time Reduction

| Scenario | Before | After | Improvement |
|----------|--------|-------|-------------|
| First Build | 15-20 min | 15-20 min | No change |
| Code Change Only | 12-15 min | 3-5 min | 70-75% |
| Dependency Update | 12-15 min | 5-8 min | 50-60% |
| Base Image Update | 12-15 min | 8-10 min | 30-40% |

### Cache Hit Rates

| Target | Expected Cache Hit Rate |
|--------|------------------------|
| runtime-cuda | 95%+ |
| runtime-cpu | 95%+ |
| core-cuda | 80-90% |
| core-cpu | 80-90% |
| complete-cuda | 70-80% |
| sageattention-builder | 60-70% |

## 🔧 Configuration Options

### Cache Types

#### Inline Cache (Default - Works everywhere)
```yaml
set: |
  *.CACHE_TYPE=inline
  *.CACHE_MODE=max
```

#### GitHub Actions Cache (CI/CD only)
```yaml
set: |
  *.CACHE_TYPE=gha
  *.CACHE_MODE=max
```

#### Registry Cache (Requires containerd driver)
```yaml
set: |
  *.CACHE_TYPE=registry
  *.CACHE_MODE=max
```

### Cache Modes

- **`max`** - Store all layers (larger cache, better performance)
- **`min`** - Store only essential layers (smaller cache, moderate performance)

## 🛠️ Usage Examples

### Local Development

```bash
# Build with default inline cache (recommended)
docker buildx bake core

# Build with inline cache (explicit)
docker buildx bake --set "*.CACHE_TYPE=inline" core

# Build with registry cache (requires containerd driver)
docker buildx bake --set "*.CACHE_TYPE=registry" core

# Build specific target with custom cache
docker buildx bake --set "*.CACHE_TYPE=inline" --set "*.CACHE_MODE=max" runtime-cuda
```

### CI/CD Pipeline

The GitHub Actions workflow automatically uses optimized cache settings:

```yaml
- name: Build and push images
  uses: docker/bake-action@v4
  with:
    set: |
      *.CACHE_TYPE=gha
      *.CACHE_MODE=max
      *.BUILDKIT_INLINE_CACHE=1
      *.DOCKER_BUILDKIT=1
```

## 🔍 Monitoring Cache Performance

### Build Logs

Look for these indicators in build logs:

```
# Good cache performance
=> [runtime-cuda 1/6] FROM nvidia/cuda:12.9.1-base-ubuntu24.04@sha256:...
=> CACHED [runtime-cuda 2/6] RUN apt-get update && apt-get install -y...
=> CACHED [runtime-cuda 3/6] RUN python3 -m venv $VENV_PATH...

# Poor cache performance
=> [runtime-cuda 1/6] FROM nvidia/cuda:12.9.1-base-ubuntu24.04@sha256:...
=> [runtime-cuda 2/6] RUN apt-get update && apt-get install -y...
=> [runtime-cuda 3/6] RUN python3 -m venv $VENV_PATH...
```

### Cache Statistics

Monitor cache hit rates in GitHub Actions:

```yaml
- name: Cache Statistics
  run: |
    echo "Cache hit rate: $(docker buildx du | grep 'Cache Size' | awk '{print $3}')"
```

## 🚨 Troubleshooting

### Common Issues

#### Cache Not Working
1. Check if BuildKit is enabled: `DOCKER_BUILDKIT=1`
2. Verify cache configuration in `docker-bake.hcl`
3. Ensure GitHub Actions cache is properly configured

#### Slow Builds
1. Check cache hit rates in build logs
2. Verify layer ordering in Dockerfiles
3. Consider using `CACHE_MODE=max` for better performance

#### Cache Size Issues
1. Use `CACHE_MODE=min` to reduce cache size
2. Clean up old cache entries periodically
3. Monitor GitHub Actions cache usage

### Debug Commands

```bash
# Check cache status
docker buildx du

# Clear all caches
docker buildx prune -a

# Inspect cache configuration
docker buildx bake --print core
```

## 📈 Best Practices

### 1. Layer Ordering
- Put rarely-changing layers first
- Group related operations together
- Use multi-stage builds effectively

### 2. Cache Strategy
- Use GitHub Actions cache for CI/CD
- Use registry cache for local development
- Enable inline cache for immediate reuse

### 3. Build Optimization
- Minimize layer count where possible
- Use `.dockerignore` to exclude unnecessary files
- Leverage BuildKit features

### 4. Maintenance
- Monitor cache hit rates regularly
- Clean up old cache entries
- Update base images strategically

## 🔮 Future Improvements

### Planned Enhancements

1. **Parallel Builds** - Build independent targets simultaneously
2. **Incremental Builds** - Only rebuild changed components
3. **Smart Cache Invalidation** - Automatic cache cleanup
4. **Build Analytics** - Detailed performance metrics

### Experimental Features

1. **Distributed Caching** - Share cache across runners
2. **Predictive Caching** - Pre-warm cache based on patterns
3. **Adaptive Cache Strategy** - Dynamic cache configuration

## 📚 References

- [Docker BuildKit Documentation](https://docs.docker.com/develop/dev-best-practices/)
- [GitHub Actions Cache](https://docs.github.com/en/actions/using-workflows/caching-dependencies-to-speed-up-workflows)
- [Docker Bake Documentation](https://docs.docker.com/build/bake/)
- [BuildKit Cache Backends](https://docs.docker.com/build/cache/backends/) 