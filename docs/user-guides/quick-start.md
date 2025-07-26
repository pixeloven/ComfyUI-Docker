# Quick Start

Get ComfyUI running in minutes.

## What is ComfyUI?

ComfyUI is a powerful node-based interface for AI image generation. This Docker setup provides GPU acceleration with CPU fallback and optional SageAttention 2++ optimization.

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
docker compose comfy-nvidia up -d        # GPU mode (recommended)
docker compose comfy-cuda-extended up -d # Extended GPU mode (2-3x faster attention)
docker compose comfy-cpu up -d    # CPU mode (universal)

# 3. Open http://localhost:8188
```

## Hardware Modes

- **GPU Mode** (`comfy-nvidia`): Fast generation, requires NVIDIA GPU
- **Extended GPU Mode** (`comfy-cuda-extended`): ⚡ **2-3x faster attention** with SageAttention 2++, requires NVIDIA GPU with 8GB+ VRAM
- **CPU Mode** (`comfy-cpu`): Works everywhere, slower generation

## SageAttention 2++ Extended Mode

The extended mode includes SageAttention 2++ for significantly faster attention computation:

### Benefits
- **2-3x faster** attention operations
- **Reduced VRAM usage** for attention
- **Better scaling** with large models
- **Automatic fallback** for incompatible operations

### Requirements
- NVIDIA GPU with 8GB+ VRAM (RTX 20 series or newer recommended)
- CUDA 12.x runtime environment

### Usage
1. Start with extended mode: `docker compose comfy-cuda-extended up -d`
2. SageAttention 2++ is automatically used by compatible models
3. No manual configuration required - seamless integration

## Basic Configuration

```bash
# Change port (default: 8188)
sed -i 's/COMFY_PORT=8188/COMFY_PORT=8080/' .env

# Low VRAM mode (4-6GB GPUs)
sed -i 's/CLI_ARGS=/CLI_ARGS=--lowvram/' .env

# CPU-only mode
sed -i 's/CLI_ARGS=/CLI_ARGS=--cpu/' .env
```
