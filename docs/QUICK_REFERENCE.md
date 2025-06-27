# Quick Reference

Essential commands and configuration for daily ComfyUI Docker usage.

## 🚀 Essential Commands

### First Time Setup
```bash
# Clone repository
git clone https://github.com/pixeloven/ComfyUI-Docker.git
cd ComfyUI-Docker

# Copy environment file
cp .env.example .env

docker compose --profile comfy-setup up -d
```

# Start ComfyUI (GPU mode)
```bash
docker compose --profile comfy up -d
# Access: http://localhost:8188
```

### Daily Usage

```bash
# Start services
docker compose --profile comfy up -d

# Stop services (preserves container state)
docker compose stop

# Restart services
docker compose restart

# View logs
docker compose logs -f

# Complete shutdown (removes containers)
docker compose down
```
> [!IMPORTANT]  
> Stopping a running container is generally safe while downing, which destroys the running container, will often break the installation. To fix start ComfyUI and use the Comfy Manager to fix each of the installed plugins. 

### Model Management
```bash
# Download models (dry run first to preview)
docker compose --profile comfy-setup up

# Actual download (edit .env: SETUP_CLI_ARGS="")
docker compose --profile comfy-setup up
```

## ⚙️ Configuration

### Key Environment Variables (.env file)
```bash
# Hardware Configuration
COMFY_CLI_ARGS=""              # GPU mode (default)
COMFY_CLI_ARGS="--cpu"         # CPU-only mode
COMFY_CLI_ARGS="--lowvram"     # Low VRAM GPU
COMFY_CLI_ARGS="--novram"      # Very low VRAM GPU

# Model Setup
SETUP_CLI_ARGS="--dry-run"     # Preview downloads
SETUP_CLI_ARGS=""              # Actual download

# System
PUID=1000                      # User ID
PGID=1000                      # Group ID
```

### Docker Profiles
- **`comfy`** - Main ComfyUI service (port 8188)
- **`comfy-setup`** - Model download utility

### Hardware Modes
```bash
# Switch to CPU mode
echo 'COMFY_CLI_ARGS="--cpu"' > .env
docker compose restart

# Switch to GPU mode
echo 'COMFY_CLI_ARGS=""' > .env
docker compose restart
```

### Data Management
```bash
# Backup your data
tar -czf comfy-backup-$(date +%Y%m%d).tar.gz ./data

# Check disk usage
docker system df

# Clean up unused images
docker system prune
```

## 🐛 Troubleshooting

### Quick Fixes
```bash
# Service won't start
docker compose logs                    # Check error messages
docker compose down && docker compose --profile comfy up -d

# Port already in use
netstat -tulpn | grep :8188           # Check what's using port 8188
# Change port in docker-compose.yml if needed

# GPU not detected
docker run --rm --gpus all nvidia/cuda:11.8-base-ubuntu20.04 nvidia-smi

# Permission errors
sudo chown -R $USER:$USER ./data ./output

# Out of memory
echo 'COMFY_CLI_ARGS="--lowvram"' > .env    # Low VRAM mode
echo 'COMFY_CLI_ARGS="--cpu"' > .env        # CPU mode
docker stats                                # Check resource usage
```

### Performance Issues
- **Slow generation**: Switch to GPU mode if available
- **Out of VRAM**: Use `--lowvram` or `--novram` flags
- **High CPU usage**: Normal for CPU mode, consider GPU upgrade

## 💡 Pro Tips

- **First run**: Initial startup downloads images (~5-10 minutes)
- **Models**: Auto-downloaded to `./data/models/`
- **Outputs**: Generated images saved to `./output/`
- **Updates**: `docker compose pull` for latest images
- **Backup**: Regularly backup `./data/` directory
- **Extensions**: Use ComfyUI Manager within the interface

## 🆘 Getting Help

1. **Check logs**: `docker compose logs -f`
2. **Verify setup**: Ensure `.env` file exists and is configured
3. **Test access**: Visit http://localhost:8188
4. **Search issues**: [GitHub Issues](https://github.com/AbdBarho/stable-diffusion-webui-docker/issues)
5. **Create issue**: Include logs, `.env` config, and system info

### Related Guides
- **[CPU Support Guide](CPU_SUPPORT.md)** - Hardware configuration details
- **[Build Guide](BUILD.md)** - Development and customization
- **[Documentation Index](README.md)** - All available guides

---

**[⬆ Back to Documentation](README.md)** | **[🏠 Main README](../README.md)**
