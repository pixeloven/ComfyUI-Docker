# CPU Support Guide

ComfyUI supports both GPU and CPU modes for maximum compatibility.

## 🚀 Quick Start

### GPU Mode (Recommended)
```bash
# Start with GPU acceleration
docker compose --profile comfy up -d
# Access: http://localhost:8188
```

### CPU Mode
```bash
# Configure for CPU-only
cp .env.example .env
echo 'COMFY_CLI_ARGS="--cpu"' >> .env

# Start CPU mode
docker compose --profile comfy-cpu up -d
# Access: http://localhost:8189
```

## ⚙️ Configuration

### Common Settings (.env file)
```bash
# CPU mode
COMFY_CLI_ARGS="--cpu"

# CPU with optimizations
COMFY_CLI_ARGS="--cpu --force-fp16"

# GPU with low VRAM
COMFY_CLI_ARGS="--lowvram"

# GPU with very low VRAM
COMFY_CLI_ARGS="--novram"

# Verbose logging
COMFY_CLI_ARGS="--verbose"
```

### Profiles & Ports
- **`comfy`** - ComfyUI → http://localhost:8188
- **`comfy-setup`** - Model download service (no web interface)

## 📊 Performance Notes

- **GPU Mode**: Fast inference, requires NVIDIA GPU with CUDA
- **CPU Mode**: Slower but works on any system
- **Memory**: GPU uses VRAM, CPU uses system RAM
- **Optimization**: Add `--force-fp16` for better CPU performance

## 🔧 Common Commands

```bash
# Switch to CPU mode
echo 'COMFY_CLI_ARGS="--cpu"' > .env
docker compose --profile comfy-cpu up -d

# Switch to GPU mode
echo 'COMFY_CLI_ARGS=""' > .env
docker compose --profile comfy up -d
```

## 🐛 Troubleshooting

### Common Issues
- **GPU not detected**: Check NVIDIA drivers and Docker GPU support
- **Port conflicts**: Modify ports in `docker-compose.yml` if needed
- **Slow CPU performance**: Expected behavior, consider smaller models
- **Memory issues**: Reduce model size or increase system RAM

### Useful Commands
```bash
# View logs
docker compose logs -f

# Check GPU availability
docker run --rm --gpus all nvidia/cuda:11.8-base-ubuntu20.04 nvidia-smi

# Switch modes
docker compose down
# Edit .env file
docker compose --profile comfy-cpu up -d  # or --profile comfy
```

For more detailed information, see [Quick Reference](QUICK_REFERENCE.md).
