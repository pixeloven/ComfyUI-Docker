# Usage

Daily operations for ComfyUI Docker.

## Daily Commands

```bash
# Start (GPU)
docker compose --profile comfy-nvidia up -d
# Start (CPU)
docker compose --profile comfy-cpu up -d

# Stop (preserves state)
docker compose stop

# Restart
docker compose restart

# View logs
docker compose logs -f

# Complete shutdown
docker compose down
```

## Switch Modes

```bash
# Switch to CPU
docker compose down
docker compose --profile comfy-cpu up -d

# Switch to GPU
docker compose down
docker compose --profile comfy-nvidia up -d
```

## Model Management

```bash
# Download models
docker compose --profile comfy-setup up

# Model locations
./data/models/     # Downloaded models
./output/          # Generated images
./data/config/     # ComfyUI settings
```

## Automatic Setup Features

The ComfyUI container automatically:

- **Installs ComfyUI Manager**: Version 3.33.8 is automatically installed for easy extension management
- **Creates Required Directories**: Sets up all necessary data and output directories
- **Configures Virtual Environment**: Runs ComfyUI in an isolated Python environment
- **Handles Permissions**: Uses PUID/PGID for proper file ownership

### Post-Install Process

The container runs a post-install script that:
1. Creates necessary directories (`/data/config/comfy`, `/output`)
2. Installs ComfyUI Manager if not present
3. Sets up proper environment variables
4. Marks completion to avoid re-running

This ensures a consistent setup across all deployments.

## Configuration

```bash
# Custom port
sed -i 's/COMFY_PORT=8188/COMFY_PORT=8080/' .env

# Performance tuning
sed -i 's/CLI_ARGS=/CLI_ARGS=--lowvram/' .env    # 4-6GB GPUs
sed -i 's/CLI_ARGS=/CLI_ARGS=--cpu/' .env        # CPU-only mode
sed -i 's/CLI_ARGS=/CLI_ARGS=--novram/' .env     # No VRAM mode

# Setup configuration
sed -i 's/SETUP_DRY_RUN=1/SETUP_DRY_RUN=0/' .env  # Enable actual downloads
```

## Troubleshooting

### Common Issues
- **Port in use**: Change `COMFY_PORT` in `.env`
- **Permission errors**: `sudo chown -R $USER:$USER ./data ./output`
- **GPU not detected**: Test with `docker run --rm --gpus all nvidia/cuda:11.8-base-ubuntu20.04 nvidia-smi`

### Diagnostic Commands
```bash
# Check container status
docker compose ps

# Test web interface
curl -f http://localhost:8188

# Check GPU (GPU mode)
docker compose exec comfy nvidia-smi
```

### Getting Help
- Check logs: `docker compose logs -f`
- Search [GitHub Issues](https://github.com/pixeloven/ComfyUI-Docker/issues)

---

**[⬆ Back to Documentation](README.md)** | **[🚀 Getting Started](GETTING_STARTED.md)** | **[⚙️ Configuration](CONFIGURATION.md)** 