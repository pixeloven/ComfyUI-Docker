# CPU Support Guide

ComfyUI supports both GPU acceleration and CPU-only modes for maximum hardware compatibility.

## 🎯 Hardware Requirements

### GPU Mode (Recommended)
- **NVIDIA GPU** with CUDA support (GTX 1060+ or RTX series)
- **8GB+ VRAM** for optimal performance (4GB minimum with `--lowvram`)
- **NVIDIA Container Toolkit** installed

### CPU Mode (Universal)
- **Any modern CPU** (Intel/AMD, x86_64 or ARM64)
- **16GB+ RAM** recommended (8GB minimum)
- **No special drivers** required

## ⚙️ Configuration

### GPU Modes (.env file)
```bash
# Standard GPU mode (8GB+ VRAM)
COMFY_CLI_ARGS=""

# Low VRAM mode (4-8GB VRAM)
COMFY_CLI_ARGS="--lowvram"

# Very low VRAM mode (2-4GB VRAM)
COMFY_CLI_ARGS="--novram"
```

### CPU Modes (.env file)
```bash
# Basic CPU mode
COMFY_CLI_ARGS="--cpu"

# Optimized CPU mode (faster, uses more RAM)
COMFY_CLI_ARGS="--cpu --force-fp16"

# CPU with verbose logging
COMFY_CLI_ARGS="--cpu --verbose"
```

## 🔄 Switching Modes

```bash
# Switch to CPU mode
echo 'COMFY_CLI_ARGS="--cpu"' > .env
docker compose restart

# Switch to GPU mode
echo 'COMFY_CLI_ARGS=""' > .env
docker compose restart

# Switch to low VRAM GPU mode
echo 'COMFY_CLI_ARGS="--lowvram"' > .env
docker compose restart
```

## 📊 Performance Comparison

| Mode | Speed | VRAM Usage | RAM Usage | Compatibility |
|------|-------|------------|-----------|---------------|
| GPU Standard | ⭐⭐⭐⭐⭐ | 6-12GB | 2-4GB | NVIDIA only |
| GPU Low VRAM | ⭐⭐⭐⭐ | 3-6GB | 4-8GB | NVIDIA only |
| GPU No VRAM | ⭐⭐⭐ | <2GB | 8-16GB | NVIDIA only |
| CPU Optimized | ⭐⭐ | 0GB | 8-16GB | Universal |
| CPU Basic | ⭐ | 0GB | 4-8GB | Universal |

## 🐛 Troubleshooting

### GPU Issues
```bash
# Test GPU availability
docker run --rm --gpus all nvidia/cuda:11.8-base-ubuntu20.04 nvidia-smi

# Check NVIDIA drivers
nvidia-smi

# Verify Docker GPU support
docker info | grep -i nvidia
```

### CPU Performance
- **Slow generation**: Expected behavior, consider GPU upgrade
- **High RAM usage**: Normal for CPU mode, ensure adequate system RAM
- **Process hanging**: Try `--force-fp16` for better stability

### Common Solutions
```bash
# Out of memory (any mode)
docker stats                           # Check resource usage
echo 'COMFY_CLI_ARGS="--cpu"' > .env   # Fallback to CPU

# Service won't start
docker compose logs -f                 # Check error messages
docker compose down && docker compose --profile comfy up -d
```

## 💡 Optimization Tips

### For GPU Users
- Use **standard mode** if you have 8GB+ VRAM
- Use **`--lowvram`** for 4-8GB VRAM cards
- Use **`--novram`** for older/low-end GPUs

### For CPU Users
- Add **`--force-fp16`** for better performance
- Ensure **16GB+ RAM** for larger models
- Consider **smaller/quantized models** for better speed

### General Tips
- **Monitor resources**: Use `docker stats` to check usage
- **Start simple**: Begin with basic settings, optimize later
- **Update regularly**: Newer versions often have performance improvements

---

**[⬆ Back to Documentation](README.md)** | **[📖 Quick Reference](QUICK_REFERENCE.md)** | **[🏠 Main README](../README.md)**
