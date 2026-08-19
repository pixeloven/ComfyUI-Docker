# ComfyUI Docker 🐳

[![GitHub Sponsors](https://img.shields.io/github/sponsors/pixeloven?style=for-the-badge&logo=github&label=Sponsor)](https://github.com/sponsors/pixeloven)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-yellow?style=for-the-badge&logo=buymeacoffee)](https://buymeacoffee.com/pixeloven)

**Production-ready Docker setup for [ComfyUI](https://github.com/Comfy-Org/ComfyUI)**

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

- **🚀 Current Accelerators**: NVIDIA CUDA 13.0, AMD ROCm 7.2, Intel XPU, and CPU
- **🎯 Versioned ComfyUI**: Stable release tags by default, explicit nightly builds when wanted
- **📁 Persistent Storage**: Individual volume mounts for models, outputs, custom nodes, etc.
- **🐳 Production Ready**: Multi-stage builds, layer caching, and pre-built GHCR images
- **⚡ Performance Optimized**: Dynamic VRAM, async offload, CUDA graphs, Comfy Kitchen, and architecture-specific SageAttention images
- **🔧 Extensible**: Custom node support via volume mounts
- **🔄 CI/CD Ready**: Automated builds, weekly dependency updates
- **🔒 Security**: Runs as non-root by default, supports Docker Compose PUID/PGID and Kubernetes securityContext

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

Choose an example directory and start the service:

**Core GPU** (recommended for most users):
```bash
cd examples/core-gpu
docker compose up -d
```

**Complete GPU** (extra custom-node dependencies):
```bash
cd examples/complete-gpu
docker compose up -d
```

**Core CPU** (no GPU required):
```bash
cd examples/core-cpu
docker compose up -d
```

### 3. Access the Interface

Open your browser to: **http://localhost:8188**

### 4. Download Models

Place your Stable Diffusion checkpoints in `./data/models/checkpoints/` or download them through the ComfyUI interface.

---

## Deployment Profiles

ComfyUI Docker offers five deployment examples to match your hardware and use case:

| Example | Container | Image | Best For | Features |
|---------|-----------|-------|----------|----------|
| **`core-gpu`** | `comfyui-core-gpu` | `ghcr.io/pixeloven/comfyui/core:cuda-latest` | Most users | Essential ComfyUI + GPU acceleration |
| **`complete-gpu`** | `comfyui-complete-gpu` | `ghcr.io/pixeloven/comfyui/complete:cuda-latest` | Power users | Pre-installed common custom-node dependencies |
| **`core-amd`** | `comfyui-core-amd` | `ghcr.io/pixeloven/comfyui/core:rocm-latest` | AMD Linux | PyTorch ROCm 7.2 |
| **`core-intel`** | `comfyui-core-intel` | `ghcr.io/pixeloven/comfyui/core:xpu-latest` | Intel Arc Linux | PyTorch XPU |
| **`core-cpu`** | `comfyui-core-cpu` | `ghcr.io/pixeloven/comfyui/core:cpu-latest` | Testing/Compatibility | No GPU required |

### Core GPU (`examples/core-gpu`) ⚡

Fast, lightweight ComfyUI with GPU support.

```bash
cd examples/core-gpu
docker compose up -d
```

- ✅ Essential ComfyUI functionality
- ✅ GPU acceleration (CUDA 13.0 / PyTorch cu130)
- ✅ Fast startup
- ✅ Smaller image size

### Complete GPU (`examples/complete-gpu`) 🚀

CUDA deployment with pre-installed Python dependencies used by common custom nodes.

```bash
cd examples/complete-gpu
docker compose up -d
```
- ✅ Everything core has
- ✅ Pre-installed Python dependencies for common custom node setups
- ✅ Current Comfy Kitchen attention backend available with `CLI_ARGS=--use-ck-attention`
- ✅ SageAttention 2.2.0 variants for Ampere through Blackwell GPUs
- ⚠️  Larger image size

For SageAttention, select the tag matching the GPU compute capability and add
`--use-sage-attention` to `CLI_ARGS`. For example, RTX 50-series (Blackwell)
uses `ghcr.io/pixeloven/comfyui/complete:cuda-sm120-latest`. See the
[Performance Tuning Guide](docs/user-guides/performance.md#sageattention) for
the full architecture table and verification steps.

### Core CPU (`examples/core-cpu`)

No GPU required, universal compatibility.

```bash
cd examples/core-cpu
docker compose up -d
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
├── datasets/        → /app/datasets        (LoRA training datasets)
├── input/           → /app/input           (Input images/workflows)
├── output/          → /app/output          (Generated outputs)
├── temp/            → /app/temp            (Temporary files)
└── user/            → /app/user            (User configurations)
```

**Customize paths** via environment variables:
```bash
COMFY_MODEL_PATH=/path/to/models \
COMFY_OUTPUT_PATH=/path/to/outputs \
docker compose up -d   # from within an examples/ directory
```

See [Data Management Guide](docs/user-guides/data.md) for details.

---

## Configuration

### Environment Variables

Common configuration options:

```bash
# Server Configuration
COMFY_PORT=8188                      # Web interface port
PUID=1000                            # User ID for file ownership (default: 1000)
PGID=1000                            # Group ID for file ownership (default: 1000)

# Performance Tuning
CLI_ARGS="--lowvram"                # ComfyUI launch arguments

# Custom Paths
COMFY_MODEL_PATH=./data/models      # Override model directory
COMFY_OUTPUT_PATH=./data/output     # Override output directory
```

**Match your host user's UID/GID** to avoid permission issues with mounted volumes:
```bash
PUID=$(id -u) PGID=$(id -g) docker compose up -d   # from within an examples/ directory
```

### Kubernetes Deployment

The images support Kubernetes natively via `securityContext.runAsUser`. When the entrypoint detects a non-root UID, it skips the gosu/PUID/PGID logic and executes directly:

```yaml
securityContext:
  runAsUser: 3000
  runAsGroup: 3000
  fsGroup: 3000
```

The Python virtual environment's package and entry-point directories are world-writable at build time, so ComfyUI Manager can install custom node dependencies regardless of the runtime UID.

**For complete configuration options, see:**
- [Running Containers Guide](docs/user-guides/running.md) - Environment variables, Docker Compose, and Kubernetes
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
- **[Custom Nodes Snapshot Spec](docs/specs/custom-nodes-snapshot-spec.md)** - How the Complete image manages bundled dependencies

### 🛠️ Development

For developers and contributors, see the [Building Images Guide](docs/user-guides/building.md) for local development and the [Contributing](#contributing) section below.

**[📖 View Full Documentation Index](docs/index.md)**

---

## Related Resources

### ComfyUI Project

- **[ComfyUI GitHub](https://github.com/comfyanonymous/ComfyUI)** - Official ComfyUI repository
- **[ComfyUI Examples](https://comfyanonymous.github.io/ComfyUI_examples/)** - Official workflow examples
- **[ComfyUI Wiki](https://github.com/comfyanonymous/ComfyUI/wiki)** - Documentation and guides

### ComfyUI Ecosystem

- **[ComfyUI Manager](https://github.com/ltdrdata/ComfyUI-Manager)** - Custom node manager
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
3. **Submit PRs**: See [Building Images Guide](docs/user-guides/building.md) for development setup
4. **Improve Docs**: Documentation PRs are always appreciated!

### Development Setup

```bash
# Clone the repository
git clone https://github.com/pixeloven/ComfyUI-Docker.git
cd ComfyUI-Docker

# Build images locally
docker buildx bake all --load

# Test a specific example
cd examples/core-gpu
docker compose up -d

# View logs
docker compose logs -f
```

**For detailed build instructions, see [Building Images Guide](docs/user-guides/building.md).**

### Contribution Guidelines

- Follow existing code style and structure
- Test your changes with all five examples
- Update documentation for new features
- Add meaningful commit messages
- Ensure CI/CD checks pass

---

## FAQ

### What is ComfyUI Docker?

ComfyUI Docker is a production-ready containerization of **[ComfyUI](https://github.com/Comfy-Org/ComfyUI)**, a node-based engine for image, video, audio, 3D, and language workflows. This project provides:

- **Multiple deployment profiles** (core, complete, CPU-only)
- **Multi-stage Docker builds** using Docker Buildx Bake
- **GPU acceleration** for NVIDIA CUDA, AMD ROCm, and Intel XPU on Linux
- **Persistent data management** with granular volume mounting
- **Pre-built images** available on GitHub Container Registry
- **Flexible configuration** via environment variables

Perfect for local development, production deployments, or CI/CD pipelines.

### Which profile should I use?

- **Core Mode**: Best for most users - fast startup, essential features, GPU acceleration
- **Complete Mode**: Best for NVIDIA power users who want common custom-node dependencies pre-installed
- **AMD/Intel Modes**: Core images using the official PyTorch ROCm or XPU wheel channels
- **CPU Mode**: Best for testing or when no GPU is available

### Do I need a GPU?

The CUDA and Complete examples require NVIDIA, the AMD example requires a ROCm-supported GPU, and the Intel example requires a supported Intel GPU. CPU mode needs no GPU but is significantly slower.

### Where are my models and outputs stored?

Everything is stored in the `./data/` directory with subdirectories for models, outputs, custom nodes, etc. You can customize these paths using environment variables. See the [Data Management Guide](docs/user-guides/data.md) for details.

### How do I add custom nodes?

Install custom nodes through the ComfyUI interface or mount them to `./data/custom_nodes/`. See the [Data Management Guide](docs/user-guides/data.md) for details.

### Can I use my own models?

Yes! Place your checkpoints, LoRAs, and other models in the appropriate subdirectories under `./data/models/`. ComfyUI will automatically detect them.

### How do I update ComfyUI?

Pull the latest image from within your example directory:
```bash
docker compose pull
docker compose up -d
```

For local builds, rebuild the images:
```bash
docker buildx bake all --no-cache
```

### Why is my container slow to start?

**Complete mode** has a larger image due to pre-installed Python dependencies. Use **Core mode** when custom nodes can manage their own dependencies.

---

## License

This project is licensed under the **[MIT License](LICENSE)**.

**ComfyUI** itself is licensed under **GPL-3.0** - see the [ComfyUI repository](https://github.com/Comfy-Org/ComfyUI/blob/master/LICENSE) for details.

---

**Questions?** Check out [GitHub Discussions](https://github.com/pixeloven/ComfyUI-Docker/discussions) or open an [issue](https://github.com/pixeloven/ComfyUI-Docker/issues).
