# Performance Tuning

Optimize ComfyUI for your hardware with CLI arguments and resource configuration.

## CLI Arguments

ComfyUI provides command-line arguments for performance tuning. Configure via the `CLI_ARGS` environment variable.

### Quick Settings

```bash
# Standard GPU (8GB+ VRAM) - in .env
CLI_ARGS=

# Low VRAM systems (4-6GB) - in .env
CLI_ARGS=--lowvram

# Ultra-low VRAM systems (<4GB) - in .env
CLI_ARGS=--novram

# CPU-only mode - in .env
CLI_ARGS=--cpu
```

Or inline:
```bash
CLI_ARGS="--lowvram" docker compose up -d
```

### Combining Arguments

Multiple arguments can be combined:

```bash
# Low VRAM + disable previews
CLI_ARGS="--lowvram --preview-method none"

# Half-precision VAE + low VRAM
CLI_ARGS="--fp16-vae --lowvram"
```

## Common Arguments

For complete documentation, see the [ComfyUI Manual Install Guide](https://docs.comfy.org/essentials/comfyui_manual_install#optional-setup).

### Memory Management

```bash
--lowvram                # For 4-6GB VRAM systems
--novram                 # For <4GB VRAM systems (slowest)
--cpu                    # Force CPU-only mode
--normalvram             # Normal VRAM usage (default)
```

### Precision Settings

```bash
--fp16-vae               # Use half-precision for VAE (saves memory)
--fp32-vae               # Use full-precision for VAE
--fp8_e4m3fn-text-enc    # Use FP8 for text encoder
--fp8_e5m2-text-enc      # Use FP8 (alternative format)
```

### Attention Mechanisms

```bash
--use-split-cross-attention     # Split attention (memory efficient)
--use-quad-cross-attention      # Quad split attention
--use-pytorch-cross-attention   # PyTorch native attention
--disable-xformers              # Disable xformers optimization
```

### Preview Settings

```bash
--preview-method auto       # Auto-select preview method (default)
--preview-method latent2rgb # Latent2RGB previews
--preview-method taesd      # TAESD previews (faster)
--preview-method none       # Disable previews (saves memory)
```

### Logging

```bash
--verbose                # Enable verbose output
```

## Recommended Configurations

### Low-End GPU (4-6GB VRAM)
```bash
CLI_ARGS=--lowvram --preview-method none --fp16-vae
```

### Mid-Range GPU (6-8GB VRAM)
```bash
CLI_ARGS=--lowvram --preview-method taesd
```

### High-End GPU (12GB+ VRAM)
```bash
CLI_ARGS=--preview-method auto
```

Use Complete mode for best performance:
```bash
cd examples/complete-gpu
docker compose up -d
```

### CPU-Only System
```bash
CLI_ARGS=--cpu --preview-method none
```

Use the CPU example:
```bash
cd examples/core-cpu
docker compose up -d
```

## SageAttention (Complete Mode Only)

The **Complete** image includes [SageAttention 2.2.0](https://github.com/thu-ml/SageAttention) and [SageAttn3 3.0.0](https://github.com/thu-ml/SageAttention) for 2-3x faster attention computation.

### Features

- **Automatic activation** - No configuration needed
- **2-3x faster** - Attention computation speedup
- **Minimal quality impact** - <1% difference
- **Smart fallback** - Uses standard attention when needed
- **Blackwell GPU support** - SageAttn3 supports NVIDIA Blackwell architecture

### Verify Installation

```bash
docker exec comfyui-complete-gpu python -c "import sageattention; print('SageAttention OK')"
```

## Docker Resource Limits

Configure resource limits in your example's `docker-compose.yml`:

### Memory Limits

```yaml
services:
  comfyui:
    deploy:
      resources:
        limits:
          memory: 16G        # Maximum RAM
        reservations:
          memory: 8G         # Reserved RAM
```

### GPU Selection

```yaml
# Use all GPUs
devices:
  - driver: nvidia
    count: all
    capabilities: [gpu]

# Use specific GPUs
devices:
  - driver: nvidia
    device_ids: ['0', '2']  # GPU 0 and 2 only
    capabilities: [gpu]
```

### CPU Limits

```yaml
deploy:
  resources:
    limits:
      cpus: '4'        # Limit to 4 CPU cores
```

## Storage Optimization

### Fast Storage for Outputs

Use fast SSD for output directory:

```bash
# In .env
COMFY_OUTPUT_PATH=/mnt/nvme/comfyui-outputs
```

### Model Loading

```bash
# Fast local storage
COMFY_MODEL_PATH=/mnt/fast-ssd/models

# Shared network storage (slower)
COMFY_MODEL_PATH=/mnt/nfs/shared-models
```

See [Data Management](data.md) for path configuration.

## Monitoring Performance

### GPU Utilization

```bash
# Real-time GPU monitoring
watch -n 1 nvidia-smi

# Inside container
docker exec comfyui-core-gpu nvidia-smi
```

### Container Resources

```bash
# Real-time stats
docker stats
```

## Common Performance Issues

### Out of Memory (OOM)

Try progressively lower memory modes:

```bash
# Try lowvram
CLI_ARGS=--lowvram

# If still failing, try novram
CLI_ARGS=--novram

# Last resort: CPU mode
CLI_ARGS=--cpu
```

### Slow Generation

- Check GPU is being used: `nvidia-smi`
- Try different attention mechanism: `CLI_ARGS="--use-pytorch-cross-attention"`
- Use Complete mode for SageAttention optimization

### Container Slow to Start

**Complete mode** has a larger image due to pre-installed Python dependencies and SageAttention. Use Core mode if you don't need the extra optimizations.

---

**External Resources:**
- [ComfyUI CLI Arguments](https://docs.comfy.org/essentials/comfyui_manual_install#optional-setup)
- [ComfyUI GitHub](https://github.com/comfyanonymous/ComfyUI)
- [SageAttention](https://github.com/thu-ml/SageAttention)

**See Also:**
- [Running Containers](running.md) - Set CLI_ARGS via environment variables
- [Data Management](data.md) - Optimize storage paths
- [Building Images](building.md) - Build with custom configurations
