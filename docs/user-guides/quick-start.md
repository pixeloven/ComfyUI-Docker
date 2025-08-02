# Quick Start Guide

Get ComfyUI running in 5 minutes with Docker Compose.

## Prerequisites

- **Docker** & **Docker Compose** installed
- **NVIDIA GPU + drivers** (for GPU modes)  
- **8GB+ VRAM** recommended for complete mode

## Launch ComfyUI

### 1. Clone & Setup
```bash
git clone https://github.com/pixeloven/ComfyUI-Docker.git
cd ComfyUI-Docker
```

### 2. Start ComfyUI (Choose One)
```bash
# Core mode (recommended - essential features with GPU acceleration)
docker compose up -d

# Complete mode (all features including optimizations and custom nodes)
docker compose --profile complete up -d

# CPU mode (universal compatibility)
docker compose --profile cpu up -d
```

### 3. Access ComfyUI
Open **http://localhost:8188** in your browser

## Usage Modes

- **Core Mode** (`core-cuda`): Essential ComfyUI with GPU acceleration, fast startup
- **Complete Mode** (`complete-cuda`): ⚡ **2-3x faster attention** with SageAttention 2++, all custom nodes included
- **CPU Mode** (`core-cpu`): Works everywhere, slower generation

## First Workflow

Once ComfyUI loads:

1. **Load Example**: Use the "Load Default" workflow button
2. **Add Models**: Place checkpoint files in `./data/models/checkpoints/`
3. **Generate**: Click "Queue Prompt" to start generation

### Quick Model Setup
1. Start with core mode: `docker compose up -d`
2. Download a checkpoint (e.g., Stable Diffusion 1.5) to `./data/models/checkpoints/`
3. Load the default workflow and select your model
4. Generate your first image!

## Data Persistence

All your data persists in `./data/`:
```
data/
├── models/          # Place model files here
├── input/           # Upload images for processing
├── output/          # Generated images appear here
├── user/            # Custom nodes and workflows
└── temp/            # Temporary processing files
```

## Next Steps

- **[Usage Guide](usage.md)** - Learn advanced workflows
- **[Configuration](configuration.md)** - Customize your setup
- **[Development](../development-guides/development.md)** - Build custom images

## Troubleshooting

**GPU not detected?**
```bash
# Check NVIDIA drivers
nvidia-smi

# Verify Docker can access GPU
docker run --rm --gpus all nvidia/cuda:11.8-runtime-ubuntu20.04 nvidia-smi
```

**Port already in use?**
```bash
# Use different port
COMFY_PORT=8189 docker compose up -d
```

**Need more help?** See the [Configuration Guide](configuration.md) for detailed troubleshooting.
