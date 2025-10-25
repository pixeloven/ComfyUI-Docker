# Configuration Guide

Customize your ComfyUI Docker setup for optimal performance.

## Environment Variables

### Core Configuration
```bash
# Port configuration
COMFY_PORT=8188                    # Web interface port

# User/Group IDs for file permissions
PUID=1000                          # User ID
PGID=1000                          # Group ID

# Individual path configuration (used by current docker-compose.yml)
COMFY_CUSTOM_NODE_PATH=./data/custom_nodes  # Custom nodes directory
COMFY_INPUT_PATH=./data/input               # Input images/workflows
COMFY_MODEL_PATH=./data/models              # AI models, checkpoints
COMFY_OUTPUT_PATH=./data/output             # Generated content
COMFY_TEMP_PATH=./data/temp                 # Temporary files
COMFY_USER_PATH=./data/user                 # User configurations

# ComfyUI startup arguments
CLI_ARGS=                          # Additional CLI arguments
```

### Performance Tuning
```bash
# GPU Memory Management
CLI_ARGS="--lowvram"               # 4-6GB VRAM systems
CLI_ARGS="--novram"                # <4GB VRAM systems  
CLI_ARGS="--cpu"                   # Force CPU-only mode

# Attention Optimization
CLI_ARGS="--use-split-cross-attention"  # Memory-efficient attention
CLI_ARGS="--use-quad-cross-attention"   # Alternative attention method

# Preview Settings
CLI_ARGS="--preview-method auto"   # Auto-select preview method
CLI_ARGS="--preview-method none"   # Disable previews (saves memory)
```

## Available Images

The project provides pre-built images on GitHub Container Registry:

| Image | Tag | Profile | Description |
|-------|-----|---------|-------------|
| `core` | `cuda-latest` | `core` (default) | Essential ComfyUI with CUDA |
| `complete` | `cuda-latest` | `complete` | Full features + custom nodes |
| `core` | `cpu-latest` | `cpu` | CPU-only mode |

Images are automatically selected based on the profile you use. Override with:

```bash
COMFY_IMAGE=ghcr.io/pixeloven/comfyui-docker/core:cuda-dev docker compose up -d
```

## SageAttention (Complete Mode Only)

The **Complete** profile includes SageAttention 2++ for 2-3x faster attention computation.

**Automatic Configuration:**
- Start Complete mode: `docker compose --profile complete up -d`
- SageAttention automatically activates for compatible operations
- Falls back to standard attention when needed
- No manual configuration required

**Verify Installation:**
```bash
docker compose exec complete-cuda python -c "import sageattention; print('SageAttention OK')"
```

## Model Paths

ComfyUI uses standard model paths under `/app/models/`:

- `checkpoints/` - Stable Diffusion checkpoints
- `loras/` - LoRA files
- `vae/` - VAE models
- `embeddings/` - Text embeddings
- `controlnet/` - ControlNet models
- `clip/` - CLIP models
- `upscale_models/` - Upscaling models
- And more...

**Custom paths** can be configured in `data/extra_model_paths.yaml` if needed.

## Docker Compose Profiles

| Profile | Command | Description |
|---------|---------|-------------|
| Core (default) | `docker compose up -d` | Essential ComfyUI + GPU |
| Complete | `docker compose --profile complete up -d` | All features + custom nodes |
| CPU | `docker compose --profile cpu up -d` | CPU-only mode |

## Network Configuration

### Port Mapping
```bash
# Custom port
COMFY_PORT=8080 docker compose up -d

# Multiple instances  
COMFY_PORT=8188 docker compose up -d    # Instance 1
COMFY_PORT=8189 docker compose up -d    # Instance 2 (different directory)
```

### External Access

**Warning:** By default, ComfyUI binds to `0.0.0.0` allowing external access. For security:

- Use a firewall or reverse proxy for production
- Consider binding to `127.0.0.1` only in docker-compose.yml
- Use authentication if exposing publicly

## Storage Configuration

### Default Volume Mounts

The docker-compose.yml mounts individual directories:

```yaml
volumes:
  - ${COMFY_CUSTOM_NODE_PATH:-./data/custom_nodes}:/app/custom_nodes:rw
  - ${COMFY_INPUT_PATH:-./data/input}:/app/input:rw
  - ${COMFY_MODEL_PATH:-./data/models}:/app/models:ro
  - ${COMFY_OUTPUT_PATH:-./data/output}:/app/output:rw
  - ${COMFY_TEMP_PATH:-./data/temp}:/app/temp:rw
  - ${COMFY_USER_PATH:-./data/user}:/app/user:rw
```

**Customize paths** using environment variables:
```bash
COMFY_MODEL_PATH=/mnt/shared/models docker compose up -d
```

## Performance Optimization

### System Resources
```yaml
# Resource limits in docker-compose.yml
deploy:
  resources:
    limits:
      memory: 16G        # Maximum RAM usage
    reservations:
      memory: 8G         # Reserved RAM
      devices:
        - driver: nvidia
          count: all     # Use all GPUs
          capabilities: [gpu]
```

### GPU Configuration
```bash
# Specific GPU selection
CLI_ARGS="--directml"              # Use DirectML (Windows)
CLI_ARGS="--force-fp16"            # Force half-precision
CLI_ARGS="--fp16-vae"              # Half-precision VAE
```

## Logging Configuration

### Log Levels
```bash
# Verbose logging
CLI_ARGS="--verbose"

# Debug mode
CLI_ARGS="--debug-mode"

# Quiet mode
CLI_ARGS="--disable-server-log"
```

### Log Management
```bash
# View logs
docker compose logs -f --tail=100

# Save logs to file
docker compose logs > comfyui.log

# Rotate logs automatically
# Add to docker-compose.yml:
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

## Security Configuration

### File Permissions
```bash
# Set proper ownership
sudo chown -R $USER:$USER ./data

# Secure permissions
chmod 755 ./data
chmod -R 644 ./data/models/*
```

### Network Security
```bash
# Local access only (default)
ports:
  - "127.0.0.1:${COMFY_PORT:-8188}:${COMFY_PORT:-8188}"

# Firewall configuration (if exposing externally)
sudo ufw allow ${COMFY_PORT}/tcp
```

## Troubleshooting Configuration

### Common Issues

**Memory errors**
```bash
# Reduce memory usage
CLI_ARGS="--lowvram --novram --cpu"
```

**Model loading issues**
```bash
# Check model paths
docker compose exec core-cuda ls -la /app/models/checkpoints/

# Verify permissions
docker compose exec core-cuda ls -la /app/
```

**GPU not detected**
```bash
# Test GPU access
docker run --rm --gpus all nvidia/cuda:11.8-runtime-ubuntu20.04 nvidia-smi

# Check Docker GPU support
docker info | grep -i nvidia
```

### Diagnostic Commands
```bash
# Container information
docker compose exec core-cuda env | grep COMFY
docker compose exec core-cuda python --version
docker compose exec core-cuda pip list | grep torch

# System information
docker compose exec core-cuda cat /proc/meminfo | head
docker compose exec core-cuda df -h
``` 