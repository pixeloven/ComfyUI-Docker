# Quick Start

Get ComfyUI running in minutes.

## What is ComfyUI?

ComfyUI is a powerful node-based interface for AI image generation. This Docker setup provides GPU acceleration with CPU fallback.

## Setup

```bash
# 1. Clone and setup
git clone https://github.com/pixeloven/ComfyUI-Docker.git
cd ComfyUI-Docker
cp .env.example .env

# 2. Start (choose one)
docker compose --profile comfy-nvidia up -d        # GPU mode (recommended)
docker compose --profile comfy-cpu up -d    # CPU mode (universal)

# 3. Open http://localhost:8188
```

## Hardware Modes

- **GPU Mode** (`comfy`): Fast generation, requires NVIDIA GPU
- **CPU Mode** (`comfy-cpu`): Works everywhere, slower generation

## Basic Configuration

```bash
# Change port (default: 8188)
echo 'COMFY_PORT=8080' >> .env

# Low VRAM mode (4-6GB GPUs)
echo 'CLI_ARGS=--lowvram' >> .env
```

## Download Models (Optional)

```bash
# Preview downloads
docker compose --profile comfy-setup up

# Actually download (edit .env: SETUP_DRY_RUN=0)
docker compose --profile comfy-setup up
``` 