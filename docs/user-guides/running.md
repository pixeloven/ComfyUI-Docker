# Running Containers

How to run ComfyUI using Docker Compose with profile selection and environment configuration.

## Quick Start

```bash
# Start with default profile (Core mode)
docker compose up -d

# Access ComfyUI
# Open http://localhost:8188 in your browser
```

## Service Profiles

ComfyUI Docker provides three deployment profiles:

| Profile | Command | Service | Description |
|---------|---------|---------|-------------|
| **Core** (default) | `docker compose up -d` | `core-cuda` | Essential ComfyUI with GPU support |
| **Complete** | `docker compose --profile complete up -d` | `complete-cuda` | Full features + 13+ custom nodes |
| **CPU** | `docker compose --profile cpu up -d` | `core-cpu` | CPU-only mode (no GPU required) |

### Profile Selection

```bash
# Core mode (default, recommended for most users)
docker compose up -d
docker compose --profile core up -d  # Explicit

# Complete mode (power users, slower first startup)
docker compose --profile complete up -d

# CPU mode (testing, no GPU required)
docker compose --profile cpu up -d
```

## Basic Operations

### Start Services

```bash
# Start in background
docker compose up -d

# Start with logs visible
docker compose up
```

### Stop Services

```bash
# Stop containers (preserves data)
docker compose down

# Stop and remove volumes (⚠️ deletes data)
docker compose down -v
```

### Restart Services

```bash
# Restart all services
docker compose restart

# Restart specific profile
docker compose restart core-cuda
docker compose restart complete-cuda
docker compose restart core-cpu
```

### View Logs

```bash
# Follow all logs
docker compose logs -f

# Follow specific service
docker compose logs -f core-cuda
docker compose logs -f complete-cuda

# Last 100 lines
docker compose logs -f --tail=100

# Search logs
docker compose logs core-cuda | grep ERROR
```

### Check Status

```bash
# View running containers
docker compose ps

# Detailed status
docker compose ps -a
```

## Environment Configuration

Configure ComfyUI using environment variables via `.env` file or inline.

### Create .env File

Create `.env` in your project root:

```bash
# Server Configuration
COMFY_PORT=8188
PUID=1000
PGID=1000

# Data Paths (individual directories)
COMFY_CUSTOM_NODE_PATH=./data/custom_nodes
COMFY_INPUT_PATH=./data/input
COMFY_MODEL_PATH=./data/models
COMFY_OUTPUT_PATH=./data/output
COMFY_TEMP_PATH=./data/temp
COMFY_USER_PATH=./data/user

# ComfyUI Arguments
CLI_ARGS=--preview-method auto

# Optional: Override image
# COMFY_IMAGE=ghcr.io/pixeloven/comfyui-docker/core:cuda-dev
```

Then start normally:
```bash
docker compose up -d
```

### Inline Environment Variables

Override settings without `.env` file:

```bash
# Custom port
COMFY_PORT=8080 docker compose up -d

# Custom model path
COMFY_MODEL_PATH=/mnt/shared/models docker compose up -d

# Multiple overrides
COMFY_PORT=8080 CLI_ARGS="--lowvram" docker compose up -d
```

### Available Environment Variables

#### Server & Setup
```bash
COMFY_PORT=8188              # Web interface port
PUID=1000                    # User ID for file ownership
PGID=1000                    # Group ID for file ownership
```

#### Data Paths
```bash
COMFY_CUSTOM_NODE_PATH=./data/custom_nodes  # Custom nodes
COMFY_INPUT_PATH=./data/input               # Input images
COMFY_MODEL_PATH=./data/models              # AI models
COMFY_OUTPUT_PATH=./data/output             # Generated content
COMFY_TEMP_PATH=./data/temp                 # Temporary files
COMFY_USER_PATH=./data/user                 # User configs
```

#### Optional Overrides
```bash
COMFY_IMAGE=custom:latest    # Override Docker image
CLI_ARGS="--lowvram"         # ComfyUI launch arguments
```

See [Performance Tuning](performance.md) for CLI_ARGS options.

## Multiple Instances

Run multiple ComfyUI instances on the same machine:

```bash
# Instance 1 (default)
cd ~/comfyui-instance-1
COMFY_PORT=8188 docker compose up -d

# Instance 2 (different directory and port)
cd ~/comfyui-instance-2
COMFY_PORT=8189 docker compose up -d
```

**Requirements:**
- Separate project directories
- Different ports (COMFY_PORT)
- Separate data directories (or shared models with different outputs)

## Container Access

### Interactive Shell

```bash
# Access running container
docker compose exec core-cuda bash
docker compose exec complete-cuda bash
docker compose exec core-cpu bash
```

### Run Commands

```bash
# Check Python version
docker compose exec core-cuda python --version

# List installed packages
docker compose exec core-cuda pip list

# Check GPU status
docker compose exec core-cuda nvidia-smi

# View environment
docker compose exec core-cuda env | grep COMFY
```

## Updates

### Using Pre-Built Images

```bash
# Pull latest images
docker compose pull

# Restart with new images
docker compose up -d

# Or combine
docker compose pull && docker compose up -d
```

### Using Local Builds

```bash
# Rebuild images
docker buildx bake all --load

# Restart containers
docker compose up -d --force-recreate
```

## Troubleshooting

### Port Already in Use

```bash
# Check what's using the port
sudo lsof -i :8188

# Use different port
COMFY_PORT=8189 docker compose up -d
```

### Container Won't Start

```bash
# Check logs for errors
docker compose logs

# Check container status
docker compose ps -a

# Validate configuration
docker compose config --quiet
```

### Permission Issues

```bash
# Fix ownership
sudo chown -R $USER:$USER ./data

# Set proper permissions
chmod -R 755 ./data
```

### GPU Not Detected

```bash
# Verify NVIDIA drivers
nvidia-smi

# Test Docker GPU support
docker run --rm --gpus all nvidia/cuda:12.6.0-runtime-ubuntu24.04 nvidia-smi

# Check container GPU access
docker compose exec core-cuda nvidia-smi
```

### Health Check

```bash
# API health check
curl -f http://localhost:8188/system_stats

# Check if service is responding
curl -I http://localhost:8188
```

---

**Next:** [Data Management](data.md) | [Performance Tuning](performance.md) | **Previous:** [Building Images](building.md)
