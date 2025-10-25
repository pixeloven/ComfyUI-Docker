# ComfyUI Docker 🐳

**Production-ready Docker setup for [ComfyUI](https://github.com/comfyanonymous/ComfyUI)**

A complete containerized deployment of ComfyUI with GPU acceleration, flexible deployment profiles, and persistent data management. Built with Docker Buildx Bake for efficient multi-stage builds.

## Table of Contents

- [Key Features](#key-features)
- [Quick Start](#quick-start)
- [Deployment Profiles](#deployment-profiles)
- [Data & Storage](#data--storage)
- [Configuration](#configuration)
- [Documentation](#documentation)
- [Related Resources](#related-resources)
- [Contributing](#contributing)
- [FAQ](#faq)
- [License](#license)


## Key Features

- **🚀 GPU-Accelerated**: NVIDIA CUDA 12.9 support with optimized runtime
- **🎯 Multiple Profiles**: Core (minimal), Complete (full-featured), CPU-only
- **📁 Persistent Storage**: Individual volume mounts for models, outputs, custom nodes, etc.
- **🐳 Production Ready**: Multi-stage builds, layer caching, and pre-built GHCR images
- **⚡ Performance Optimized**: SageAttention for 2-3x faster attention computation
- **🔧 Extensible**: Custom node support via snapshot system
- **🔄 CI/CD Ready**: Automated builds, weekly dependency updates

---

## Quick Start

### Prerequisites

- **Docker** 20.10+ and **Docker Compose** 2.x
- **NVIDIA GPU + drivers** (for GPU modes) - [Install Guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
- **8GB+ VRAM** recommended for complete mode
- **20GB+ disk space** for models and images

### 1. Clone the Repository

```bash
git clone https://github.com/pixeloven/ComfyUI-Docker.git
cd ComfyUI-Docker
```

### 2. Launch ComfyUI

**Core Mode** (recommended for most users):
```bash
docker compose up -d
```

**Complete Mode** (all features + custom nodes):
```bash
docker compose --profile complete up -d
```

**CPU Mode** (no GPU required):
```bash
docker compose --profile cpu up -d
```

### 3. Access the Interface

Open your browser to: **http://localhost:8188**

### 4. Download Models

Place your Stable Diffusion checkpoints in `./data/models/checkpoints/` or download them through the ComfyUI interface.

---

## Deployment Profiles

ComfyUI Docker offers three deployment profiles to match your use case:

| Profile | Service | Image | Best For | Features |
|---------|---------|-------|----------|----------|
| **Core** | `core-cuda` | `ghcr.io/pixeloven/comfyui-docker/core:cuda-latest` | Most users | Essential ComfyUI + GPU acceleration |
| **Complete** | `complete-cuda` | `ghcr.io/pixeloven/comfyui-docker/complete:cuda-latest` | Power users | Custom nodes + SageAttention + pre-installed workflows |
| **CPU** | `core-cpu` | `ghcr.io/pixeloven/comfyui-docker/core:cpu-latest` | Testing/Compatibility | No GPU required |

### Core Mode (`core-cuda`) ⚡

Fast, lightweight ComfyUI with GPU support.

```bash
docker compose up -d
```

- ✅ Essential ComfyUI functionality
- ✅ GPU acceleration (CUDA 12.9)
- ✅ Fast startup
- ✅ Smaller image size

### Complete Mode (`complete-cuda`) 🚀

Full-featured deployment with custom nodes and optimizations.

```bash
docker compose --profile complete up -d
```
- ✅ Everything core has
- ✅ 13+ pre-installed custom nodes
- ✅ SageAttention optimization (2-3x faster)
- ⚠️  Larger image and longer startup

**Included Custom Nodes:**
- ComfyUI-Custom-Scripts, rgthree-comfy, ComfyUI-KJNodes
- ComfyUI-Impact-Pack, ComfyUI-IPAdapter-plus
- ComfyUI_UltimateSDUpscale, ComfyUI-IC-Light
- [Full list in scripts documentation](docs/user-guides/scripts.md)

### CPU Mode (`core-cpu`)

No GPU required, universal compatibility.

```bash
docker compose --profile cpu up -d
```

- ✅ Works without NVIDIA GPU
- ⚠️  Slower generation times
- ✅ Lower resource requirements

---

## Data & Storage

ComfyUI Docker uses **individual volume mounts** for each data directory, providing granular control:

```
./data/
├── models/          → /app/models          (AI models, checkpoints, LoRAs)
├── custom_nodes/    → /app/custom_nodes    (Extensions and plugins)
├── input/           → /app/input           (Input images/workflows)
├── output/          → /app/output          (Generated outputs)
├── temp/            → /app/temp            (Temporary files)
└── user/            → /app/user            (User configurations)
```

**Customize paths** via environment variables:
```bash
COMFY_MODEL_PATH=/path/to/models \
COMFY_OUTPUT_PATH=/path/to/outputs \
docker compose up -d
```

See [Data Management Guide](docs/user-guides/data.md) for details.

---

## Configuration

### Environment Variables

Common configuration options:

```bash
# Server Configuration
COMFY_PORT=8188                      # Web interface port
PUID=1000                            # User ID for file ownership
PGID=1000                            # Group ID for file ownership

# Performance Tuning
CLI_ARGS="--lowvram"                # ComfyUI launch arguments

# Custom Paths
COMFY_MODEL_PATH=./data/models      # Override model directory
COMFY_OUTPUT_PATH=./data/output     # Override output directory
```

**For complete configuration options, see:**
- [Running Containers Guide](docs/user-guides/running.md) - Environment variables and Docker Compose
- [Performance Tuning Guide](docs/user-guides/performance.md) - CLI arguments and optimization

---

## Documentation

### 📚 User Guides

**Getting Started:**
- **[Quick Start](docs/user-guides/quick-start.md)** - Get running in 5 minutes

**Core Guides:**
- **[Building Images](docs/user-guides/building.md)** - Build locally or use pre-built GHCR images
- **[Running Containers](docs/user-guides/running.md)** - Docker Compose operations and `.env` configuration
- **[Data Management](docs/user-guides/data.md)** - Models, workflows, and persistent storage
- **[Performance Tuning](docs/user-guides/performance.md)** - CLI arguments and resource optimization

**Advanced:**
- **[Scripts Guide](docs/user-guides/scripts.md)** - Custom node installation for Complete mode

### 🛠️ Development Guides

For developers and contributors:

- **[Development](docs/development-guides/development.md)** - Build images, contribute code
- **[CI/CD](docs/development-guides/ci-cd.md)** - Build system and automation

### 📊 Project Management

Planning and analysis:

- **[Tasks](docs/project-management/tasks.md)** - Roadmap and technical debt
- **[Repository Analysis](docs/project-management/repository-analysis.md)** - Comparison with other projects
- **[Custom Nodes Migration](docs/project-management/custom-nodes-migration.md)** - Snapshot-based installation plan

**[📖 View Full Documentation Index](docs/index.md)**

---

## Related Resources

### ComfyUI Project

- **[ComfyUI GitHub](https://github.com/comfyanonymous/ComfyUI)** - Official ComfyUI repository
- **[ComfyUI Examples](https://comfyanonymous.github.io/ComfyUI_examples/)** - Official workflow examples
- **[ComfyUI Wiki](https://github.com/comfyanonymous/ComfyUI/wiki)** - Documentation and guides

### ComfyUI Ecosystem

- **[ComfyUI Manager](https://github.com/ltdrdata/ComfyUI-Manager)** - Custom node manager
- **[ComfyUI CLI](https://github.com/Comfy-Org/comfy-cli)** - Official command-line tool
- **[Civitai](https://civitai.com/)** - Model sharing platform

### Docker & NVIDIA

- **[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/)** - GPU support for Docker
- **[Docker Buildx](https://docs.docker.com/build/buildx/)** - Build system documentation
- **[Docker Compose](https://docs.docker.com/compose/)** - Compose reference

---

## Contributing

We welcome contributions! Whether it's bug reports, feature requests, documentation improvements, or code contributions.

### How to Contribute

1. **Report Issues**: Use [GitHub Issues](https://github.com/pixeloven/ComfyUI-Docker/issues) with our templates
2. **Suggest Features**: Open a [Feature Request](https://github.com/pixeloven/ComfyUI-Docker/issues/new?template=feature.md)
3. **Submit PRs**: See [Development Guide](docs/development-guides/development.md) for setup
4. **Improve Docs**: Documentation PRs are always appreciated!

### Development Setup

```bash
# Clone the repository
git clone https://github.com/pixeloven/ComfyUI-Docker.git
cd ComfyUI-Docker

# Build images locally
docker buildx bake all

# Test a specific profile
docker compose --profile core up -d

# View logs
docker compose logs -f core-cuda
```

**For detailed development instructions, see [Development Guide](docs/development-guides/development.md).**

### Contribution Guidelines

- Follow existing code style and structure
- Test your changes with all three profiles
- Update documentation for new features
- Add meaningful commit messages
- Ensure CI/CD checks pass

---

## FAQ

### What is ComfyUI Docker?

ComfyUI Docker is a production-ready containerization of **[ComfyUI](https://github.com/comfyanonymous/ComfyUI)**, a powerful node-based interface for Stable Diffusion and other AI image generation models. This project provides:

- **Multiple deployment profiles** (core, complete, CPU-only)
- **Multi-stage Docker builds** using Docker Buildx Bake
- **GPU acceleration** with NVIDIA CUDA support
- **Persistent data management** with granular volume mounting
- **Pre-built images** available on GitHub Container Registry
- **Flexible configuration** via environment variables

Perfect for local development, production deployments, or CI/CD pipelines.

### Which profile should I use?

- **Core Mode**: Best for most users - fast startup, essential features, GPU acceleration
- **Complete Mode**: Best for power users - includes 13+ custom nodes, SageAttention optimization
- **CPU Mode**: Best for testing or when no GPU is available

### Do I need a GPU?

For **Core** and **Complete** modes, yes - an NVIDIA GPU with CUDA support is required. For **CPU mode**, no GPU is needed, but image generation will be significantly slower.

### Where are my models and outputs stored?

Everything is stored in the `./data/` directory with subdirectories for models, outputs, custom nodes, etc. You can customize these paths using environment variables. See the [Data Management Guide](docs/user-guides/data.md) for details.

### How do I add custom nodes?

**Core mode**: Install custom nodes through the ComfyUI interface or mount them to `./data/custom_nodes/`

**Complete mode**: 13+ custom nodes are pre-installed. See the [Scripts Guide](docs/user-guides/scripts.md) for the full list and how to add more.

### Can I use my own models?

Yes! Place your checkpoints, LoRAs, and other models in the appropriate subdirectories under `./data/models/`. ComfyUI will automatically detect them.

### How do I update ComfyUI?

Pull the latest image:
```bash
docker compose pull
docker compose up -d
```

For local builds, rebuild the images:
```bash
docker buildx bake all --no-cache
```

### Why is my container slow to start?

**Complete mode** performs post-install scripts on first startup. This is normal and only happens once. Subsequent startups will be fast. Consider using **Core mode** if you don't need the extra custom nodes.

---

## License

This project is licensed under the **[MIT License](LICENSE)**.

**ComfyUI** itself is licensed under **GPL-3.0** - see the [ComfyUI repository](https://github.com/comfyanonymous/ComfyUI/blob/master/LICENSE) for details.

---

**Questions?** Check out [GitHub Discussions](https://github.com/pixeloven/ComfyUI-Docker/discussions) or open an [issue](https://github.com/pixeloven/ComfyUI-Docker/issues).
