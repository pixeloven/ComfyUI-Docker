# Quick Reference

Essential commands and configuration for daily ComfyUI Docker usage.

## � Overview

- **Essential Commands** - Daily usage commands for setup and operation
- **Configuration** - Environment variables and hardware modes
- **Troubleshooting** - Quick fixes for common issues
- **Pro Tips** - Best practices and helpful hints

## �🚀 Essential Commands

### First Time Setup
```bash
# Clone and setup
git clone https://github.com/pixeloven/ComfyUI-Docker.git
cd ComfyUI-Docker
cp .env.example .env

# Download models (optional)
docker compose --profile comfy-setup up

# Start ComfyUI (GPU mode)
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
# Preview model downloads (default behavior)
docker compose --profile comfy-setup up

# Actual download (edit .env: SETUP_DRY_RUN=0)
docker compose --profile comfy-setup up
```

## ⚙️ Configuration

### Key Environment Variables (.env file)
```bash
# Model Setup
SETUP_DRY_RUN=1               # Preview downloads (default)
SETUP_DRY_RUN=0               # Actual download

# System
PUID=1000                     # User ID
PGID=1000                     # Group ID
COMFY_PORT=8188               # Web interface port
```

### Hardware Configuration
The project now uses dedicated service profiles instead of CLI arguments:
- **`comfy`** - GPU mode (default)
- **`comfy-cpu`** - CPU-only mode

### Service Profiles
- **`comfy`** - GPU-accelerated ComfyUI (configurable port, default 8188)
- **`comfy-cpu`** - CPU-only ComfyUI (configurable port, default 8188)
- **`comfy-setup`** - Model download utility

### Hardware Mode Switching
```bash
# Switch to CPU mode
docker compose --profile comfy-cpu up -d

# Switch to GPU mode
docker compose --profile comfy up -d

# Stop current service first if switching
docker compose down
```

### Port Configuration
```bash
# Use custom port (edit .env file)
echo 'COMFY_PORT=8080' >> .env
docker compose --profile comfy up -d
# Access: http://localhost:8080

# Or set temporarily
COMFY_PORT=8080 docker compose --profile comfy up -d
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
# Service won't start check for log errors
docker compose logs

# Kill the container and restart
docker compose down 
docker compose --profile comfy up -d

# Port already in use
netstat -tulpn | grep :8188           # Check what's using port 8188
# Change port in docker-compose.yml if needed

# GPU not detected
docker run --rm --gpus all nvidia/cuda:11.8-base-ubuntu20.04 nvidia-smi

# Permission errors
sudo chown -R $USER:$USER ./data ./output
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
4. **Search issues**: [GitHub Issues](https://github.com/pixeloven/ComfyUI-Docker/issues)
5. **Create issue**: Include logs, `.env` config, and system info



---

**[⬆ Back to Documentation](README.md)** | **[🏠 Main README](../README.md)** | **[🐛 Report Issues](https://github.com/pixeloven/ComfyUI-Docker/issues)**
