# Quick Start Guide

Get ComfyUI running in 5 minutes.

## Prerequisites

- **Docker** 20.10+ & **Docker Compose** 2.x installed
- **NVIDIA GPU + drivers** (for GPU modes) - [Installation Guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
- **8GB+ VRAM** recommended for complete mode
- **20GB+ disk space** for models and outputs

## Setup

### 1. Clone Repository

```bash
git clone https://github.com/pixeloven/ComfyUI-Docker.git
cd ComfyUI-Docker
```

### 2. Start ComfyUI

Choose a profile based on your needs:

```bash
# Core Mode (recommended - essential features)
docker compose up -d

# Complete Mode (all features + 13+ custom nodes)
docker compose --profile complete up -d

# CPU Mode (no GPU required)
docker compose --profile cpu up -d
```

### 3. Access ComfyUI

Open **http://localhost:8188** in your browser

## Profile Comparison

| Profile | Startup Time | Features | Best For |
|---------|--------------|----------|----------|
| **Core** | Fast | Essential ComfyUI + GPU | Most users |
| **Complete** | Slower (first time) | 13+ custom nodes, SageAttention | Power users |
| **CPU** | Fast | No GPU required | Testing, compatibility |

## First Workflow

### Download a Model

Download a Stable Diffusion checkpoint from:
- [Civitai](https://civitai.com/)
- [Hugging Face](https://huggingface.co/models?pipeline_tag=text-to-image)

Place in: `./data/models/checkpoints/`

### Generate Your First Image

1. **Load Default Workflow**: Click "Load Default" in ComfyUI
2. **Select Model**: Choose your checkpoint in the workflow
3. **Queue Prompt**: Click "Queue Prompt" to generate
4. **View Output**: Images save to `./data/output/`

## Data Structure

All data persists in `./data/`:

```
data/
├── models/
│   ├── checkpoints/     # Main SD models (.safetensors, .ckpt)
│   ├── loras/          # LoRA files
│   └── vae/            # VAE files
├── custom_nodes/       # Custom node extensions
├── input/              # Input images for workflows
├── output/             # Generated images
└── user/               # User configs and workflows
```

See [Data Management](data.md) for detailed directory structure.

## Common Commands

```bash
# View logs
docker compose logs -f

# Stop ComfyUI
docker compose down

# Restart ComfyUI
docker compose restart

# Update to latest image
docker compose pull && docker compose up -d
```

See [Running Containers](running.md) for all Docker Compose operations.

## Next Steps

- **[Running Containers](running.md)** - Profile selection and environment configuration
- **[Data Management](data.md)** - Organize models and workflows
- **[Performance Tuning](performance.md)** - Optimize for your hardware
- **[Scripts Guide](scripts.md)** - Custom nodes in Complete mode

---

**Need Help?** [Open an issue](https://github.com/pixeloven/ComfyUI-Docker/issues) or check [GitHub Discussions](https://github.com/pixeloven/ComfyUI-Docker/discussions).
