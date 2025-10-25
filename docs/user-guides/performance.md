# Performance Tuning

Optimize ComfyUI Docker for your hardware with CLI arguments and resource configuration.

## Quick Performance Settings

### GPU Memory Optimization

ComfyUI provides CLI arguments to manage GPU memory usage. Configure via the `CLI_ARGS` environment variable:

```bash
# Standard GPU (8GB+ VRAM)
docker compose up -d

# Low VRAM systems (4-6GB)
CLI_ARGS="--lowvram" docker compose up -d

# Ultra-low VRAM systems (<4GB)
CLI_ARGS="--novram" docker compose up -d

# CPU-only mode (no GPU)
CLI_ARGS="--cpu" docker compose up -d
```

**In .env file:**
```bash
CLI_ARGS=--lowvram
```

### Combining Arguments

Multiple CLI arguments can be combined:

```bash
# Low VRAM + disable previews for max memory savings
CLI_ARGS="--lowvram --preview-method none" docker compose up -d

# Half-precision VAE + low VRAM
CLI_ARGS="--fp16-vae --lowvram" docker compose up -d
```

## ComfyUI CLI Arguments

ComfyUI supports numerous command-line arguments for performance tuning. Below are the most commonly used options for Docker deployments.

**For complete argument documentation, see:**
- [ComfyUI Command Line Arguments](https://docs.comfy.org/essentials/comfyui_manual_install#optional-setup)
- [ComfyUI GitHub README](https://github.com/comfyanonymous/ComfyUI#command-line-arguments)

### Memory Management

```bash
# VRAM optimization
--lowvram                # For 4-6GB VRAM systems
--novram                 # For <4GB VRAM systems (slowest)
--cpu                    # Force CPU-only mode
--normalvram             # Normal VRAM usage (default)

# Precision settings
--fp16-vae               # Use half-precision for VAE
--fp32-vae               # Use full-precision for VAE
--fp8_e4m3fn-text-enc    # Use FP8 for text encoder
--fp8_e5m2-text-enc      # Use FP8 (alternative format)
```

### Attention Mechanisms

```bash
# Attention optimization (memory vs speed tradeoffs)
--use-split-cross-attention     # Split attention (memory efficient)
--use-quad-cross-attention      # Quad split attention
--use-pytorch-cross-attention   # PyTorch native attention
--disable-xformers              # Disable xformers optimization
```

### Preview Settings

```bash
# Preview configuration
--preview-method auto    # Auto-select preview method (default)
--preview-method latent2rgb  # Latent2RGB previews
--preview-method taesd   # TAESD previews (faster)
--preview-method none    # Disable previews (saves memory)
```

### Verbose Logging

```bash
# Logging options
--verbose                # Enable verbose output
```

### Example Configurations

```bash
# Low-end GPU (4GB VRAM)
CLI_ARGS="--lowvram --preview-method none --fp16-vae"

# Mid-range GPU (6-8GB VRAM)
CLI_ARGS="--lowvram --preview-method taesd"

# High-end GPU (12GB+ VRAM)
CLI_ARGS="--preview-method auto"

# CPU-only system
CLI_ARGS="--cpu --preview-method none"
```

## SageAttention (Complete Mode Only)

The **Complete** profile includes [SageAttention 2++](https://github.com/thu-ml/SageAttention) for 2-3x faster attention computation with minimal quality impact.

### Automatic Activation

SageAttention is pre-installed and activates automatically:

```bash
# Start Complete mode
docker compose --profile complete up -d

# SageAttention automatically used when applicable
# Falls back to standard attention when needed
```

### Verify Installation

```bash
# Check SageAttention is available
docker compose exec complete-cuda python -c "import sageattention; print('SageAttention OK')"
```

### Performance Impact

- **Speed**: 2-3x faster attention computation
- **Quality**: Minimal impact (<1% difference)
- **Compatibility**: Automatically detects compatible operations
- **No configuration needed**

## Docker Resource Limits

Configure Docker resource limits in [docker-compose.yml](../../docker-compose.yml):

```yaml
services:
  core-cuda:
    deploy:
      resources:
        limits:
          memory: 16G        # Maximum RAM
        reservations:
          memory: 8G         # Reserved RAM
          devices:
            - driver: nvidia
              count: all     # Use all GPUs
              capabilities: [gpu]
```

### Specific GPU Selection

```yaml
# Use specific GPUs
devices:
  - driver: nvidia
    device_ids: ['0', '2']  # GPU 0 and 2 only
    capabilities: [gpu]
```

### CPU Limits

```yaml
# Limit CPU cores
deploy:
  resources:
    limits:
      cpus: '4'        # Limit to 4 CPU cores
```

## Monitoring Performance

### GPU Utilization

```bash
# Real-time GPU monitoring
watch -n 1 nvidia-smi

# Inside container
docker compose exec core-cuda nvidia-smi

# Detailed GPU info
nvidia-smi dmon -s pucvmet
```

### Container Resources

```bash
# Real-time container stats
docker stats

# Specific service stats
docker stats comfyui-docker-core-cuda-1
```

### System Performance

```bash
# Check system load
docker compose exec core-cuda top

# Memory usage
docker compose exec core-cuda free -h

# Disk I/O
docker compose exec core-cuda iostat
```

## Storage Performance

### Fast Storage for Outputs

Use fast SSD for output directory:

```bash
# Mount output to NVMe SSD
COMFY_OUTPUT_PATH=/mnt/nvme/comfyui-outputs docker compose up -d
```

### Model Loading Optimization

```bash
# Keep models on fast storage
COMFY_MODEL_PATH=/mnt/fast-ssd/models docker compose up -d

# Models on network storage (slower but shared)
COMFY_MODEL_PATH=/mnt/nfs/shared-models docker compose up -d
```

## Network Performance

### Local Access Only

For maximum performance, bind to localhost only:

```yaml
# In docker-compose.yml
ports:
  - "127.0.0.1:8188:8188"
```

### External Access

If exposing externally, use reverse proxy (nginx, Caddy) for:
- SSL/TLS termination
- Request caching
- Load balancing

## Troubleshooting Performance

### Out of Memory (OOM) Errors

```bash
# Reduce memory usage progressively
CLI_ARGS="--lowvram" docker compose up -d
CLI_ARGS="--novram" docker compose up -d
CLI_ARGS="--cpu" docker compose up -d

# Also reduce preview memory
CLI_ARGS="--lowvram --preview-method none" docker compose up -d
```

### Slow Generation Times

```bash
# Check GPU utilization
nvidia-smi

# Ensure GPU is being used
docker compose exec core-cuda nvidia-smi

# Try different attention mechanism
CLI_ARGS="--use-pytorch-cross-attention" docker compose up -d
```

### Container Startup is Slow

**Complete mode first startup:**
- Expected: Scripts install custom nodes (2-5 minutes)
- Subsequent startups are fast

**Core mode:**
- Should start quickly
- Check logs: `docker compose logs -f`

### Disk Space Issues

```bash
# Check disk usage
du -sh ./data/*

# Clean old outputs
rm -rf ./data/output/*

# Clean temp files
rm -rf ./data/temp/*
```

## Performance Benchmarking

### Compare Settings

```bash
# Benchmark with different settings
time docker compose exec core-cuda python benchmark.py

# Test different CLI args
CLI_ARGS="--lowvram" docker compose restart
# Run test workflow, note time
CLI_ARGS="--use-split-cross-attention" docker compose restart
# Run test workflow, note time
```

### System Stats API

```bash
# Check system performance via API
curl http://localhost:8188/system_stats | jq

# Monitor during generation
watch -n 1 'curl -s http://localhost:8188/system_stats | jq'
```

## Recommended Configurations

### Development Machine
```bash
# .env
CLI_ARGS=--preview-method auto
COMFY_PORT=8188
```

### Low-End GPU (4-6GB VRAM)
```bash
# .env
CLI_ARGS=--lowvram --preview-method none --fp16-vae
```

### High-End GPU (12GB+ VRAM)
```bash
# .env
CLI_ARGS=--preview-method auto
# Use Complete mode for best performance
docker compose --profile complete up -d
```

### CPU-Only Server
```bash
# .env
CLI_ARGS=--cpu --preview-method none
docker compose --profile cpu up -d
```

---

**Previous:** [Data Management](data.md) | [Running Containers](running.md) | [Building Images](building.md)

**External Resources:**
- [ComfyUI CLI Arguments](https://docs.comfy.org/essentials/comfyui_manual_install#optional-setup)
- [ComfyUI GitHub](https://github.com/comfyanonymous/ComfyUI)
- [SageAttention](https://github.com/thu-ml/SageAttention)
