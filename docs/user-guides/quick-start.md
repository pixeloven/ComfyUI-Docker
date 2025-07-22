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

## Model Management

Model management is now handled through custom nodes within ComfyUI. The comfy-setup service has been deprecated in favor of integrated model management. 

## GPU Addons Image

A new GPU-specific image, `comfy-nvidia-addons`, is available for users who want pre-installed GPU-specific addons (see `addon-requirements.txt`).

**To use the GPU image with addons:**

```bash
docker run --rm --gpus all -v $(pwd)/data:/data -v $(pwd)/output:/output -p 8188:8188 ghcr.io/pixeloven/comfyui-docker/comfy-nvidia-addons:latest
```

- This image is based on the standard GPU build but includes additional Python packages for GPU features/extensions.
- Use this image if you require the GPU-specific addons listed in `addon-requirements.txt`.
- For most users, the standard `comfy-nvidia` image is sufficient unless you need these extra features. 