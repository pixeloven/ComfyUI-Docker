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

## Custom Image Selection

### Override Default Images
```bash
# Use specific image versions
COMFY_IMAGE=ghcr.io/pixeloven/comfyui-docker/core:cuda-latest docker compose up -d

# Use CPU-optimized image for testing  
COMFY_IMAGE=ghcr.io/pixeloven/comfyui-docker/core:cpu-latest docker compose --profile cpu up -d

# Use complete package with all features
COMFY_IMAGE=ghcr.io/pixeloven/comfyui-docker/complete:cuda-latest docker compose --profile complete up -d
```

## SageAttention Configuration

The complete package includes SageAttention 2++ for 2-3x faster attention computation.

### Automatic Configuration
1. **Use the complete image**: `docker compose --profile complete up -d`
2. SageAttention is automatically enabled for compatible operations
3. No manual configuration required

### Verification
```bash
# Check if SageAttention is loaded
docker compose exec complete-cuda python -c "import sageattention; print('SageAttention OK')"

# View SageAttention logs
docker compose logs complete-cuda | grep -i sage

# Test attention performance
docker compose exec complete-cuda python -c "
import torch
from sageattention import sageattn
print('SageAttention test passed')
"
```

### Fallback Behavior
- SageAttention automatically falls back to standard attention for incompatible operations
- No workflow modifications needed
- Seamless integration with existing models

## Model Path Configuration

### Default Paths
```yaml
# data/extra_model_paths.yaml (if using custom model paths)
base_path: /app/

checkpoints: models/checkpoints
vae: models/vae
loras: models/loras
embeddings: models/embeddings
controlnet: models/controlnet
clip: models/clip
clip_vision: models/clip_vision
diffusers: models/diffusers
style_models: models/style_models
upscale_models: models/upscale_models
```

### Custom Paths
```yaml
# Add custom model directories
custom_nodes: user/custom_nodes
workflows: user/workflows  
scripts: user/scripts
```

## Docker Compose Profiles

### Available Profiles
```bash
# Default profile (core mode)
docker compose up -d

# Core profile (explicit)
docker compose --profile core up -d

# Complete profile with all features
docker compose --profile complete up -d

# CPU-only profile  
docker compose --profile cpu up -d
```

## Network Configuration

### Port Mapping
```bash
# Custom port
COMFY_PORT=8080 docker compose up -d

# Multiple instances  
COMFY_PORT=8188 docker compose up -d    # Instance 1
COMFY_PORT=8189 docker compose up -d    # Instance 2 (different directory)
```

### Network Access
```bash
# Allow external access (security risk!)
# Modify docker-compose.yml ports section:
ports:
  - "0.0.0.0:${COMFY_PORT:-8188}:${COMFY_PORT:-8188}"
```

## Storage Configuration

### Volume Mounts
```yaml
# Default mounts in docker-compose.yml (individual subdirectory mounting)
volumes:
  - /etc/localtime:/etc/localtime:ro       # System timezone
  - /etc/timezone:/etc/timezone:ro         # System timezone
  - ${COMFY_CUSTOM_NODE_PATH:-./data/custom_nodes}:/app/custom_nodes:rw
  - ${COMFY_INPUT_PATH:-./data/input}:/app/input:rw
  - ${COMFY_MODEL_PATH:-./data/models}:/app/models:ro
  - ${COMFY_OUTPUT_PATH:-./data/output}:/app/output:rw
  - ${COMFY_TEMP_PATH:-./data/temp}:/app/temp:rw
  - ${COMFY_USER_PATH:-./data/user}:/app/user:rw
  - ./services/comfy/complete/scripts:/app/scripts:ro  # Scripts
```

### Custom Mounts
```yaml
# Add custom volume mounts (adjust paths to match current structure)
volumes:
  - ./custom-models:/app/models/custom:ro     # Read-only model library
  - ./shared-workflows:/app/user/workflows:rw # Shared workflow directory
  - /fast-storage/temp:/app/temp:rw           # High-speed temp storage
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