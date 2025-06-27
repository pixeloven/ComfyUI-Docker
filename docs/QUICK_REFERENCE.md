# Quick Reference

Essential commands and configuration for ComfyUI Docker setup.

## 📁 Directory Structure

```
stable-diffusion-webui-docker/
├── docker-compose.yml          # Main service configuration
├── .env.example               # Environment template
├── .env                       # Your configuration (create from .env.example)
├── services/
│   ├── comfy/                 # ComfyUI Docker configuration
│   └── comfy-setup/           # Model download and setup service
├── docs/                      # Documentation files
├── data/                      # Models, configurations (auto-created)
└── output/                    # Generated images (auto-created)
```

## 🚀 Getting Started

### Initial Setup
```bash
# Clone repository
git clone https://github.com/pixeloven/ComfyUI-Docker.git
cd ComfyUI-Docker

# Copy environment file
cp .env.example .env

docker compose --profile comfy-setup up -d
```

### Start ComfyUI
```bash
# ComfyUI
docker compose --profile comfy up -d
# Access: http://localhost:8188
```

### Stop Services
```bash
docker compose stop
```
Stopping the container should maintain the state of the container and thefore any plugins installed while it was running. If you need to reset the container you can use `docker compose down` to remove the container and then start it again. 

> [!IMPORTANT]  
> Stopping a running container is generally safe while downing, which destroys the running container, will often break the installation. To fix start ComfyUI and use the Comfy Manager to fix each of the installed plugins. 

### Model Setup (Optional)
```bash
# Download models using setup service (dry run first)
docker compose --profile comfy-setup up

# Actual download (remove --dry-run from .env)
# Edit .env: SETUP_CLI_ARGS=""
docker compose --profile comfy-setup up
```

## ⚙️ Configuration

### Environment Variables (.env file)
```bash
# ComfyUI Configuration
# CPU mode
COMFY_CLI_ARGS="--cpu"

# GPU with low VRAM
COMFY_CLI_ARGS="--lowvram"

# GPU with very low VRAM
COMFY_CLI_ARGS="--novram"

# CPU with optimizations
COMFY_CLI_ARGS="--cpu --force-fp16"

# Verbose logging
COMFY_CLI_ARGS="--verbose"

# Setup Service Configuration
# Dry run (preview downloads)
SETUP_CLI_ARGS="--dry-run"

# Actual download
SETUP_CLI_ARGS=""

# User/Group IDs
PUID=1000
PGID=1000
```

### Docker Compose Profiles
- `comfy` - GPU mode (port 8188)
- `comfy-setup` - Model download and setup service

## 🔧 Common Commands

### Service Management
```bash
# Start GPU service
docker compose --profile comfy up -d

# Stop all services
docker compose stop

# View logs
docker compose logs -f

# Restart service
docker compose restart
```

### Building Images
```bash
# Build comfy image
docker compose --profile comfy build

# Build comfy-setup service
docker compose --profile comfy-setup build
```

### Data Management
```bash
# View mounted volumes
docker compose config --volumes

# Backup data directory
tar -czf comfy-backup.tar.gz ./data

# Restore data directory
tar -xzf comfy-backup.tar.gz
```

## 🐛 Troubleshooting

### Common Issues

#### Service Won't Start
```bash
# Check logs
docker compose logs

# Check if port is in use
netstat -tulpn | grep :8188

# Restart Docker
sudo systemctl restart docker  # Linux
# or restart Docker Desktop
```

#### GPU Not Detected
```bash
# Check NVIDIA runtime
docker run --rm --gpus all nvidia/cuda:11.8-base-ubuntu20.04 nvidia-smi
```

#### Permission Issues
```bash
# Fix file permissions
sudo chown -R $USER:$USER ./data ./output
```

#### Out of Memory
```bash
# Use low VRAM mode
echo 'COMFY_CLI_ARGS="--lowvram"' >> .env

# Use CPU mode
echo 'COMFY_CLI_ARGS="--cpu"' >> .env

# Check system resources
docker stats
```

## 🔗 Useful Links

- **ComfyUI GitHub**: https://github.com/comfyanonymous/ComfyUI
- **ComfyUI Documentation**: https://github.com/comfyanonymous/ComfyUI#features
- **Docker Documentation**: https://docs.docker.com/
- **Docker Compose Reference**: https://docs.docker.com/compose/

## 💡 Tips

1. **First Run**: Initial startup may take longer as Docker downloads images
2. **Models**: Place models in `./data/models/` directory
3. **Outputs**: Generated images appear in `./output/` directory
4. **Updates**: Pull latest images with `docker compose pull` or build them yourself with `docker compose build`
5. **Backup**: Regularly backup your `./data/` directory
6. **Performance**: Use GPU mode for best performance, CPU mode for compatibility

## 🆘 Getting Help

1. **Check logs**: `docker compose logs`
2. **Review configuration**: Verify `.env` file settings
3. **Test connectivity**: Verify service is accessible at http://localhost:8188
4. **Search issues**: Check existing GitHub issues
5. **Create issue**: Provide logs and configuration details

For detailed documentation, see:
- [CPU Support Guide](CPU_SUPPORT.md) - Comprehensive GPU/CPU configuration
- [Local CI Testing](LOCAL_CI_TESTING.md) - Test GitHub Actions locally
