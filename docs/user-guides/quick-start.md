# Quick Start

Get ComfyUI running in minutes.

## What is ComfyUI?

ComfyUI is a powerful node-based interface for AI image generation. This Docker setup provides GPU acceleration with CPU fallback.

## Setup

```bash
# 1. Clone and setup
git clone https://github.com/pixeloven/ComfyUI-Docker.git
cd ComfyUI-Docker

# Create .env file with default settings
cat > .env << EOF
# User/Group IDs for container permissions
PUID=1000
PGID=1000

# ComfyUI Configuration
COMFY_PORT=8188
CLI_ARGS=

# Setup Configuration
SETUP_DRY_RUN=1
EOF

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
sed -i 's/COMFY_PORT=8188/COMFY_PORT=8080/' .env

# Low VRAM mode (4-6GB GPUs)
sed -i 's/CLI_ARGS=/CLI_ARGS=--lowvram/' .env

# CPU-only mode
sed -i 's/CLI_ARGS=/CLI_ARGS=--cpu/' .env
```

## Download Models (Optional)

```bash
# Preview downloads (default)
docker compose --profile comfy-setup up

# Actually download models
sed -i 's/SETUP_DRY_RUN=1/SETUP_DRY_RUN=0/' .env
docker compose --profile comfy-setup up
``` 