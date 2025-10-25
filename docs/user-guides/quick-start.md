# Quick Start Guide

Get ComfyUI running in 5 minutes with Docker Compose.

## Prerequisites

- **Docker** 20.10+ & **Docker Compose** 2.x installed
- **NVIDIA GPU + drivers** (for GPU modes) - [Installation Guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
- **8GB+ VRAM** recommended for complete mode
- **20GB+ disk space** for models and outputs

## Launch ComfyUI

### 1. Clone Repository
```bash
git clone https://github.com/pixeloven/ComfyUI-Docker.git
cd ComfyUI-Docker
```

### 2. Start ComfyUI

**Core Mode** (recommended - essential features):
```bash
docker compose up -d
```

**Complete Mode** (all features + 13+ custom nodes):
```bash
docker compose --profile complete up -d
```

**CPU Mode** (no GPU required):
```bash
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

You'll need at least one Stable Diffusion checkpoint. Download from:
- [Civitai](https://civitai.com/)
- [Hugging Face](https://huggingface.co/models?pipeline_tag=text-to-image)

Place checkpoint in: `./data/models/checkpoints/`

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
│   ├── vae/            # VAE files
│   └── ...             # Other model types
├── custom_nodes/       # Custom node extensions
├── input/              # Input images for workflows
├── output/             # Generated images
├── temp/               # Temporary files
└── user/               # User configs and workflows
```

## Common Commands

```bash
# View logs
docker compose logs -f

# Stop ComfyUI
docker compose down

# Restart ComfyUI
docker compose restart

# Update to latest image
docker compose pull
docker compose up -d
```

## Next Steps

- **[Usage Guide](usage.md)** - Daily operations and advanced workflows
- **[Configuration](configuration.md)** - Customize ports, paths, and performance
- **[Scripts Guide](scripts.md)** - Understand custom nodes in Complete mode

## Troubleshooting

### GPU Not Detected

**Check NVIDIA drivers:**
```bash
nvidia-smi
```

**Verify Docker GPU support:**
```bash
docker run --rm --gpus all nvidia/cuda:12.6.0-runtime-ubuntu24.04 nvidia-smi
```

**Install NVIDIA Container Toolkit** if needed:
- [Official Guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

### Port Already in Use

```bash
# Use different port
COMFY_PORT=8189 docker compose up -d
```

### Container Won't Start

```bash
# Check logs for errors
docker compose logs

# Check container status
docker compose ps
```

### Out of Memory Errors

```bash
# Use low VRAM mode
CLI_ARGS="--lowvram" docker compose up -d
```

**Need more help?** See the [Configuration Guide](configuration.md) or open an [issue](https://github.com/pixeloven/ComfyUI-Docker/issues).

---

**[⬆ Back to Documentation](../index.md)** | **[📖 Usage Guide](usage.md)** | **[⚙️ Configuration](configuration.md)**
