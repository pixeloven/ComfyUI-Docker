# Usage

Daily operations for ComfyUI Docker.

## Daily Commands

```bash
# Start (GPU)
docker compose comfy-nvidia up -d
# Start (CPU)
docker compose comfy-cpu up -d

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
docker compose comfy-cpu up -d

# Switch to GPU
docker compose down
docker compose comfy-nvidia up -d
```

## Model Management

```bash
# Model locations
./data/models/     # Downloaded models
./output/          # Generated images
./data/config/     # ComfyUI settings
```

**Note**: Model management is now handled through custom nodes. The comfy-setup service has been deprecated in favor of integrated model management within ComfyUI.

## Automatic Setup Features

The ComfyUI container automatically:

- **Installs ComfyUI Manager**: Version 3.33.8 is automatically installed for easy extension management
- **Creates Required Directories**: Sets up all necessary data and output directories
- **Configures Virtual Environment**: Runs ComfyUI in an isolated Python environment
- **Handles Permissions**: Uses PUID/PGID for proper file ownership

### Post-Install Process

The container runs a modular post-install script system that:
1. Creates necessary directories (`/data/config/comfy`, `/output`)
2. Installs ComfyUI Manager if not present
3. Executes additional setup scripts from mounted volumes
4. Sets up proper environment variables
5. Marks completion to avoid re-running

This ensures a consistent setup across all deployments.

## Bootstrap Scripts

The ComfyUI Docker system includes a powerful script management system for customizing container setup. Scripts are automatically executed during startup with colored logging and error handling.

### Quick Overview

- **Organized**: Scripts stored in `scripts/category/` directories  
- **Ordered**: Execute alphabetically by category, then by filename
- **Logged**: Colored output with INFO, SUCCESS, WARNING, ERROR levels
- **Protected**: Run once per container (unless forced to re-run)

### Getting Started

See the **[📜 Scripts Guide](scripts.md)** for complete documentation on:
- Creating custom scripts with colored logging
- Script templates and best practices  
- Common use cases and examples
- Troubleshooting and debugging

## Configuration

```bash
# Custom port
sed -i 's/COMFY_PORT=8188/COMFY_PORT=8080/' .env

# Performance tuning
sed -i 's/CLI_ARGS=/CLI_ARGS=--lowvram/' .env    # 4-6GB GPUs
sed -i 's/CLI_ARGS=/CLI_ARGS=--cpu/' .env        # CPU-only mode
sed -i 's/CLI_ARGS=/CLI_ARGS=--novram/' .env     # No VRAM mode

# Performance tuning
sed -i 's/CLI_ARGS=/CLI_ARGS=--lowvram/' .env    # 4-6GB GPUs
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
