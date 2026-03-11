# Running Containers

How to run ComfyUI using Docker Compose with profile selection and environment configuration.

## Deployment Examples

ComfyUI Docker provides three example configurations in the `examples/` directory:

| Example | Directory | Container | Description |
|---------|-----------|-----------|-------------|
| **Core GPU** | `examples/core-gpu` | `comfyui-core-gpu` | Essential ComfyUI with GPU support |
| **Complete GPU** | `examples/complete-gpu` | `comfyui-complete-gpu` | Pre-installed deps + SageAttention |
| **Core CPU** | `examples/core-cpu` | `comfyui-core-cpu` | CPU-only mode (no GPU required) |

### Starting Services

Navigate to your chosen example directory, then run:

```bash
cd examples/core-gpu    # or complete-gpu, core-cpu
docker compose up -d
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
# Restart the service
docker compose restart
```

### Viewing Logs

```bash
# Follow logs
docker compose logs -f

# Last 100 lines
docker compose logs --tail=100

# Or use the container name directly
docker logs -f comfyui-core-gpu
```

## Environment Configuration

Configure ComfyUI using environment variables via `.env` file or inline.

### Using .env File

Create `.env` in your example directory (e.g., `examples/core-gpu/.env`):

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

Then start normally from that directory:
```bash
docker compose up -d
```

### Inline Environment Variables

Override settings without `.env` file (from within your example directory):

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

## User Identity

The entrypoint supports two modes for controlling the runtime user identity, selected automatically based on how the container starts.

### Docker Compose: PUID/PGID (Root Entrypoint)

When the container starts as root (the default for Docker Compose), the entrypoint uses `gosu` to create and drop privileges to the specified PUID/PGID. This ensures files in mounted volumes have correct ownership.

```bash
# Method 1: Inline environment variables (from within your example directory)
PUID=$(id -u) PGID=$(id -g) docker compose up -d

# Method 2: .env file (in your example directory)
echo "PUID=$(id -u)" >> .env
echo "PGID=$(id -g)" >> .env
docker compose up -d

# Method 3: Specific UID/GID (e.g., shared NAS server)
PUID=3000 PGID=3000 docker compose up -d
```

If PUID/PGID are not specified, the container defaults to UID 1000 and GID 1000, which matches the first non-root user on most Linux systems.

### Kubernetes: securityContext (Non-Root Entrypoint)

When the container starts as a non-root user (e.g., via Kubernetes `securityContext.runAsUser`), the entrypoint detects this and skips all gosu/PUID/PGID logic. It activates the Python virtual environment and executes directly as the assigned UID.

```yaml
# Kubernetes Pod spec example
spec:
  securityContext:
    fsGroup: 3000
  containers:
    - name: comfyui
      image: ghcr.io/pixeloven/comfyui/core:cuda-latest
      securityContext:
        runAsUser: 3000
        runAsGroup: 3000
```

No PUID/PGID environment variables are needed in this mode — the UID/GID comes from the Kubernetes security context. The `fsGroup` setting ensures volume mounts are group-accessible.

### Arbitrary UID Support

The image supports running as any UID without prior configuration:

- **`/etc/passwd` injection**: The entrypoint dynamically adds a passwd entry for unknown UIDs so that Python's `getpass.getuser()`, `os.path.expanduser("~")`, and PyTorch's cache directory resolution all work correctly.
- **World-writable directories**: `site-packages`, `.cache` are writable by any UID at build time so ComfyUI Manager can install custom node dependencies and uv/pip can cache packages.
- **File ownership**: All files under `/app` are owned by the `comfy` user (UID 1000) at build time. Runtime file creation in mounted volumes uses the effective UID.

### Verification

```bash
# Docker Compose: check container user
docker exec comfyui-core-gpu id
# Expected: uid=3000(comfy) gid=3000(comfy) groups=3000(comfy)

# Check file ownership
ls -la ./data/output/
# Files should be owned by your PUID:PGID
```

## Multiple Instances

Run multiple ComfyUI instances on the same machine by copying example directories:

```bash
# Instance 1 (default)
cd ~/comfyui-instance-1    # copy of examples/core-gpu
COMFY_PORT=8188 docker compose up -d

# Instance 2 (different directory and port)
cd ~/comfyui-instance-2    # another copy of examples/core-gpu
COMFY_PORT=8189 docker compose up -d
```

**Requirements:**
- Separate project directories
- Different ports (COMFY_PORT)
- Separate data directories (or shared models with different outputs)

## Updating

### Using Pre-Built Images

From within your example directory:

```bash
# Pull latest images
docker compose pull

# Restart with new images
docker compose up -d
```

### Using Local Builds

```bash
# Rebuild images (from repository root)
docker buildx bake all --load

# Restart containers (from your example directory)
docker compose up -d --force-recreate
```

See [Building Images](building.md) for build details.

## Troubleshooting

### Port Already in Use

```bash
# Use different port (from within your example directory)
COMFY_PORT=8189 docker compose up -d

# Or check what's using the port
sudo lsof -i :8188
```

### Container Won't Start

```bash
# Check logs (from within your example directory)
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

# Or set PUID/PGID in .env (Docker Compose only)
PUID=1000
PGID=1000
```

See [Data Management](data.md) for file permission details.

### GPU Not Detected

```bash
# Verify NVIDIA drivers
nvidia-smi

# Test Docker GPU support
docker run --rm --gpus all nvidia/cuda:12.9.1-runtime-ubuntu24.04 nvidia-smi
```

See [Performance Tuning](performance.md) for GPU optimization.

---

**See Also:**
- [Building Images](building.md) - Build or pull images
- [Data Management](data.md) - Directory structure and paths
- [Performance Tuning](performance.md) - CLI arguments and optimization
