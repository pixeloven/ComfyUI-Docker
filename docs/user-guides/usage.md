# Usage Guide

Advanced usage patterns and workflows for ComfyUI Docker.

## Service Management

### Basic Operations
```bash
# Start services
docker compose up -d                      # Core mode (default)
docker compose --profile core up -d       # Core mode (explicit)
docker compose --profile complete up -d   # Complete mode with all features
docker compose --profile cpu up -d        # CPU mode

# Stop services  
docker compose down

# View logs
docker compose logs -f                    # All services
docker compose logs -f core-cuda          # Core mode
docker compose logs -f complete-cuda      # Complete mode
docker compose logs -f core-cpu           # CPU mode

# Restart services
docker compose restart
```

### Available Profiles
```bash
# Default (core mode)
docker compose up -d                      # core-cuda: Essential ComfyUI with GPU

# Core profile (same as default)
docker compose --profile core up -d       # core-cuda: Explicit core mode

# Complete profile
docker compose --profile complete up -d   # complete-cuda: All features + optimizations

# CPU profile  
docker compose --profile cpu up -d        # core-cpu: CPU-only mode
```

## Data Management

### Model Organization
```bash
# Your data directory structure
data/
├── models/
│   ├── checkpoints/         # Main model files (.safetensors, .ckpt)
│   ├── loras/              # LoRA files
│   ├── embeddings/         # Text embeddings
│   ├── vae/                # VAE files
│   ├── controlnet/         # ControlNet models
│   └── clip/               # CLIP models
├── input/                  # Upload images here
├── output/                 # Generated images
├── user/                   # Custom nodes, workflows
└── temp/                   # Temporary files
```

### Workflow Management
```bash
# Workflows are stored in data/user/
data/user/
├── default/
│   └── workflows/          # Your workflow files (.json)
└── custom_nodes/           # Custom ComfyUI nodes
```

## Performance Optimization

### GPU Memory Management
```bash
# Low VRAM systems (4-6GB)
CLI_ARGS="--lowvram" docker compose up -d

# Ultra-low VRAM systems (<4GB)  
CLI_ARGS="--novram" docker compose up -d

# CPU-only fallback
CLI_ARGS="--cpu" docker compose up -d
```

### Advanced Configuration
```bash
# Custom model paths
# Edit data/extra_model_paths.yaml

# Custom startup arguments
CLI_ARGS="--preview-method auto --use-split-cross-attention" docker compose up -d
```

## Development & Debugging

### Container Access
```bash
# Access running container
docker compose exec core-cuda bash         # Core mode
docker compose exec complete-cuda bash     # Complete mode
docker compose exec core-cpu bash          # CPU mode

# Run specific commands
docker compose exec core-cuda python --version
docker compose exec core-cpu pip list
```

### Log Analysis
```bash
# View real-time logs
docker compose logs -f --tail=100

# Filter logs by service
docker compose logs core-cuda | grep ERROR
docker compose logs complete-cuda | grep WARNING
docker compose logs core-cpu | grep INFO
```

## Maintenance

### Updates
```bash
# Pull latest images
docker compose pull

# Rebuild if needed
docker compose build --no-cache

# Update and restart
docker compose pull && docker compose up -d
```

### Cleanup
```bash
# Remove unused containers
docker system prune

# Remove unused images  
docker image prune

# Full cleanup (careful!)
docker system prune -a
```

## Integration Examples

### Custom Scripts
```bash
#!/bin/bash
# Auto-start with custom configuration

export COMFY_PORT=8188
export CLI_ARGS="--preview-method auto"

docker compose --profile complete up -d
echo "ComfyUI Complete started on http://localhost:$COMFY_PORT"
```

### API Usage
```python
# Example Python integration
import requests
import json

# ComfyUI API endpoint
api_url = "http://localhost:8188"

# Check status
status = requests.get(f"{api_url}/system_stats")
print(f"System status: {status.json()}")
```

## Troubleshooting

### Common Issues

**Port conflicts**
```bash
# Use different port
COMFY_PORT=8189 docker compose up -d
```

**Memory issues**
```bash
# Reduce memory usage
CLI_ARGS="--lowvram --preview-method none" docker compose up -d
```

**Permission issues**
```bash
# Fix file permissions
sudo chown -R $USER:$USER ./data
```

### Logs & Diagnostics
```bash
# Check container health
docker compose ps

# Detailed container info
docker compose exec core-cuda env

# System resource usage
docker stats
``` 
