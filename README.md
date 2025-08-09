# ComfyUI Docker 🐳

**Production-ready ComfyUI with Docker Compose**

A complete Docker setup for [ComfyUI](https://github.com/comfyanonymous/ComfyUI) with GPU acceleration, custom nodes, and workflow management.

## Features ✨

- **🚀 GPU-Accelerated**: NVIDIA CUDA support with optimized attention mechanisms  
- **🔧 Custom Nodes**: Pre-installed workflow enhancers, detection tools, and more
- **📁 Persistent Storage**: Models, workflows, and outputs saved to `./data/`
- **🐳 Production Ready**: Multi-stage builds with proper caching
- **⚡ SageAttention**: 2-3x faster attention computation on supported GPUs
- **🏷️ Versioned Releases**: Semantic versioning with automated Docker image builds and major/minor version tags

## Quick Start 🏃‍♂️

### Prerequisites
- Docker & Docker Compose
- NVIDIA GPU + drivers (for GPU modes)
- 8GB+ VRAM recommended for complete mode

### Launch ComfyUI

**Core Mode (Recommended)** ⚡
```bash
git clone https://github.com/pixeloven/ComfyUI-Docker.git
cd ComfyUI-Docker
docker compose up -d
```

**Complete Mode (All Features)**
```bash
docker compose --profile complete up -d
```

**CPU Mode**
```bash
docker compose --profile cpu up -d
```

Access ComfyUI at: **http://localhost:8188**

## Usage Modes 🎯

### Overview

| Mode | Service | Profile | Image | Description |
|------|---------|---------|--------|-------------|
| **Core** | `core-cuda` | `--profile core` (default) | `ghcr.io/.../core:cuda-latest` | Essential ComfyUI with GPU |
| **Complete** | `complete-cuda` | `--profile complete` | `ghcr.io/.../complete:cuda-latest` | Full package with optimizations |
| **CPU** | `core-cpu` | `--profile cpu` | `ghcr.io/.../core:cpu-latest` | CPU-only mode |

### Core Mode (`core-cuda`) ⚡

**Best for**: Most users, standard workflows
- ✅ Essential ComfyUI functionality
- ✅ GPU acceleration
- ✅ Fast startup and lighter resource usage
- ✅ All core features you need

```bash
docker compose up -d
# or explicitly: docker compose --profile core up -d
```

### Complete Mode (`complete-cuda`) 🚀

**Best for**: Production workflows, heavy processing, power users
- ✅ All custom nodes included
- ✅ SageAttention optimization (2-3x faster)
- ✅ GPU-accelerated generation  
- ✅ Pre-installed models and workflows
- ⚠️  Larger download and resource usage

```bash
docker compose --profile complete up -d
```

### CPU Mode (`core-cpu`)

**Best for**: Testing, compatibility, no GPU available
- ✅ Universal compatibility
- ⚠️  Slower generation times
- ✅ Lower resource requirements

```bash
docker compose --profile cpu up -d
```

## Data & Storage 💾

Everything persists in `./data/`:
```
data/
├── models/          # Checkpoints, LoRAs, embeddings
├── input/           # Upload images here  
├── output/          # Generated images
├── user/            # Custom nodes, workflows
└── temp/            # Temporary files
```

## Development 🛠️

See [Development Guide](docs/development-guides/development.md) for:
- Building custom images
- Adding custom nodes
- Local development setup
- Contributing guidelines

## Versioning & Releases 🏷️

This project uses semantic versioning with automated releases:

- **Release Process**: [Release Guide](docs/development-guides/releases.md)
- **Versioned Images**: All Docker images are tagged with version numbers
- **Latest**: Always use `latest` tag for the most recent build
- **Automatic Detection**: Uses commit message patterns `(MAJOR)` and `(MINOR)` for version detection

### Using Specific Versions

```bash
# Exact version
COMFY_IMAGE=ghcr.io/pixeloven/comfyui-docker/core:cuda-v1.0.0 docker compose up -d

# Latest patch in minor version
COMFY_IMAGE=ghcr.io/pixeloven/comfyui-docker/core:cuda-v1.0 docker compose up -d

# Latest minor in major version
COMFY_IMAGE=ghcr.io/pixeloven/comfyui-docker/core:cuda-v1 docker compose up -d

# Use latest (default)
docker compose up -d
```

## Documentation 📚

- **[Quick Start Guide](docs/user-guides/quick-start.md)** - Get up and running fast
- **[Configuration](docs/user-guides/configuration.md)** - Customize your setup  
- **[Usage Guide](docs/user-guides/usage.md)** - Advanced usage patterns
- **[Development](docs/development-guides/development.md)** - Build and customize

## License 📄

Licensed under [MIT License](LICENSE). ComfyUI is licensed under GPL-3.0.
