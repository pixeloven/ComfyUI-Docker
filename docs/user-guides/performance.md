# Performance Tuning

Optimize ComfyUI for your hardware with CLI arguments and resource configuration.

## CLI Arguments

ComfyUI provides command-line arguments for performance tuning. Configure via the `CLI_ARGS` environment variable.

### Quick Settings

```bash
# Standard GPU (8GB+ VRAM) - in .env
CLI_ARGS=

# Leave Dynamic VRAM enabled; reserve additional headroom for the desktop
CLI_ARGS="--vram-headroom 1"

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
--lowvram                # Legacy text-encoder offload when Dynamic VRAM is disabled
--novram                 # For <4GB VRAM systems (slowest)
--cpu                    # Force CPU-only mode
--normalvram             # Normal VRAM usage (default)
--vram-headroom 1        # Keep an extra 1 GB free for Dynamic VRAM
--disable-dynamic-vram   # Return to estimate-based model loading
--fast-disk              # Prefer disk-backed offload on a fast NVMe device
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
--use-ck-attention              # Maintained Comfy Kitchen attention backend
--use-sage-attention            # SageAttention (matching sm* image required)
--disable-xformers              # Disable xformers optimization
```

### Preview Settings

```bash
--preview-method auto       # Auto-select preview method
--preview-method latent2rgb # Latent2RGB previews
--preview-method taesd      # TAESD previews (faster)
--preview-method none       # Disable previews (default; saves memory)
```

### Logging

```bash
--verbose                # Enable verbose output
```

## Recommended Configurations

### Low-End GPU (4-6GB VRAM)
```bash
CLI_ARGS="--vram-headroom 0.5 --preview-method none --fp16-vae"
```

### Mid-Range GPU (6-8GB VRAM)
```bash
CLI_ARGS="--vram-headroom 1 --preview-method taesd"
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

## Current Acceleration Backends

ComfyUI enables Dynamic VRAM and NVIDIA async offload by default when the
hardware supports them. It also ships the maintained Comfy Kitchen kernels.

### Features

- `CLI_ARGS=--use-ck-attention` selects Comfy Kitchen attention.
- `CLI_ARGS=--use-sage-attention` selects SageAttention when using one of the
  architecture-specific Complete images described below.
- `CLI_ARGS=--fast` enables all experimental optimizations; use named options
  such as `--fast fp16_accumulation` when you want narrower risk.
- `CLI_ARGS=--disable-cuda-graphs` disables the current CUDA graph path when a
  workflow or custom node is incompatible.

### Verify Installation

```bash
docker exec comfyui-core-gpu python -c "import torch; print(torch.__version__, torch.version.cuda)"
```

### SageAttention

SageAttention 2.2.0 is available in immutable Complete image variants built
for CUDA 13.0, PyTorch 2.13, Python 3.12, and one NVIDIA compute capability.
The generic `complete:cuda-latest` image intentionally does not contain
SageAttention because a wheel compiled for one architecture is not portable to
every CUDA GPU.

| Compute capability | Common GPU families | Image tag |
| --- | --- | --- |
| `sm80` | A100, A30 | `complete:cuda-sm80-latest` |
| `sm86` | RTX 30-series, A40 | `complete:cuda-sm86-latest` |
| `sm89` | RTX 40-series, L4, L40 | `complete:cuda-sm89-latest` |
| `sm90` | H100, H200 | `complete:cuda-sm90-latest` |
| `sm120` | RTX 50-series | `complete:cuda-sm120-latest` |

Check the compute capability before choosing an image:

```bash
nvidia-smi --query-gpu=name,compute_cap --format=csv,noheader
```

Then set both the image and ComfyUI flag. For an RTX 50-series GPU:

```bash
COMFY_IMAGE=ghcr.io/pixeloven/comfyui/complete:cuda-sm120-latest \
CLI_ARGS=--use-sage-attention \
docker compose up -d
```

Verify the installed wheel matches the selected image and ComfyUI selected the
backend:

```bash
docker compose exec comfyui python -c \
  "import importlib.metadata as m; print(m.version('sageattention'))"
docker compose logs comfyui | grep "Using sage attention"
```

These wheels are published separately by
[SageAttention-Wheels](https://github.com/pixeloven/SageAttention-Wheels) and
are checksum-pinned by each image target. SageAttention is opt-in because
performance and numerical behavior vary by model and workload; compare it with
Comfy Kitchen and PyTorch attention on a representative workflow.

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
- Try `--use-ck-attention` on compatible hardware

### Container Slow to Start

**Complete mode** has a larger image due to pre-installed custom-node dependencies. The core ComfyUI acceleration paths are available in both Core and Complete.

---

**External Resources:**
- [ComfyUI CLI Arguments](https://docs.comfy.org/essentials/comfyui_manual_install#optional-setup)
- [ComfyUI GitHub](https://github.com/comfyanonymous/ComfyUI)

**See Also:**
- [Running Containers](running.md) - Set CLI_ARGS via environment variables
- [Data Management](data.md) - Optimize storage paths
- [Building Images](building.md) - Build with custom configurations
