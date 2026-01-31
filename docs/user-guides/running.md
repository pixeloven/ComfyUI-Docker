# Running Containers

How to run ComfyUI using Docker Compose with profile selection and environment configuration.

## Service Profiles

ComfyUI Docker provides three deployment profiles:

| Profile | Command | Service | Description |
|---------|---------|---------|-------------|
| **Core** (default) | `docker compose up -d` | `core-cuda` | Essential ComfyUI with GPU support |
| **Complete** | `docker compose --profile complete up -d` | `complete-cuda` | Full features + 13+ custom nodes |
| **CPU** | `docker compose --profile cpu up -d` | `core-cpu` | CPU-only mode (no GPU required) |

### Starting Services

```bash
# Core mode (default, recommended)
docker compose up -d

# Complete mode (power users)
docker compose --profile complete up -d

# CPU mode (testing, no GPU)
docker compose --profile cpu up -d
```

Access ComfyUI at: **http://localhost:8188**

### Stopping Services

```bash
# Stop containers (preserves data)
docker compose down

# Stop and remove volumes (⚠️ deletes data)
docker compose down -v
```

### Restarting Services

```bash
# Restart all services
docker compose restart

# Restart specific service
docker compose restart core-cuda
```

### Viewing Logs

```bash
# Follow logs
docker compose logs -f

# Specific service
docker compose logs -f core-cuda

# Last 100 lines
docker compose logs --tail=100
```

## Environment Configuration

Configure ComfyUI using environment variables via `.env` file or inline.

### Using .env File

Create `.env` in your project root:

```bash
# Server Configuration
COMFY_PORT=8188
PUID=1000
PGID=1000

# Data Paths
COMFY_CUSTOM_NODE_PATH=./data/custom_nodes
COMFY_INPUT_PATH=./data/input
COMFY_MODEL_PATH=./data/models
COMFY_OUTPUT_PATH=./data/output
COMFY_TEMP_PATH=./data/temp
COMFY_USER_PATH=./data/user

# Performance (see Performance Tuning guide)
CLI_ARGS=--preview-method auto

# Optional: Override image
# COMFY_IMAGE=ghcr.io/pixeloven/comfyui/core:cuda-dev
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

See [Data Management](data.md) for details on directory structure.

#### Performance & Optional
```bash
CLI_ARGS="--lowvram"         # ComfyUI launch arguments
COMFY_IMAGE=custom:latest    # Override Docker image
```

See [Performance Tuning](performance.md) for CLI_ARGS options.

## User ID / Group ID (PUID/PGID)

Run the container with your host user's UID/GID to ensure files created in mounted volumes have correct ownership.

### Why Use PUID/PGID?

When the container creates files (outputs, caches, etc.) in mounted volumes, those files are owned by the container's runtime user. Setting PUID/PGID to match your host user prevents permission issues.

### Usage

```bash
# Method 1: Environment variables
PUID=$(id -u) PGID=$(id -g) docker compose up -d

# Method 2: .env file
echo "PUID=$(id -u)" >> .env
echo "PGID=$(id -g)" >> .env
docker compose up -d

# Method 3: Specific UID/GID (e.g., shared server)
PUID=3000 PGID=3000 docker compose up -d
```

### Defaults

If PUID/PGID are not specified, the container defaults to UID 1000 and GID 1000, which matches the first non-root user on most Linux systems.

### Verification

```bash
# Check container user
docker exec comfyui-core-gpu id
# Expected: uid=3000(comfy) gid=3000(comfy) groups=3000(comfy)

# Check file ownership
ls -la ./data/output/
# Files should be owned by your PUID:PGID
```

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

## Updating

### Using Pre-Built Images

```bash
# Pull latest images
docker compose pull

# Restart with new images
docker compose up -d
```

### Using Local Builds

```bash
# Rebuild images
docker buildx bake all --load

# Restart containers
docker compose up -d --force-recreate
```

See [Building Images](building.md) for build details.

## Troubleshooting

### Port Already in Use

```bash
# Use different port
COMFY_PORT=8189 docker compose up -d

# Or check what's using the port
sudo lsof -i :8188
```

### Container Won't Start

```bash
# Check logs
docker compose logs

# Validate configuration
docker compose config --quiet

# Check container status
docker compose ps -a
```

### Permission Issues

```bash
# Fix ownership (use your PUID:PGID)
sudo chown -R $USER:$USER ./data

# Or set in .env
PUID=1000
PGID=1000
```

See [Data Management](data.md) for file permission details.

### GPU Not Detected

```bash
# Verify NVIDIA drivers
nvidia-smi

# Test Docker GPU support
docker run --rm --gpus all nvidia/cuda:12.6.0-runtime-ubuntu24.04 nvidia-smi
```

See [Performance Tuning](performance.md) for GPU optimization.

---

**See Also:**
- [Building Images](building.md) - Build or pull images
- [Data Management](data.md) - Directory structure and paths
- [Performance Tuning](performance.md) - CLI arguments and optimization
