# Quick Reference

Essential commands and configuration for ComfyUI Docker setup.

## 🚀 Getting Started

### Initial Setup
```bash
# Clone repository
git clone <repo-url>
cd stable-diffusion-webui-docker

# Copy environment file
cp .env.example .env
```

### Start ComfyUI
```bash
# GPU mode (recommended)
docker compose --profile comfy up -d
# Access: http://localhost:8188

# CPU mode
echo 'COMFY_CLI_ARGS="--cpu"' >> .env
docker compose --profile comfy-cpu up -d
# Access: http://localhost:8189
```

### Stop Services
```bash
docker compose down
```

## ⚙️ Configuration

### Environment Variables (.env file)
```bash
# CPU mode
COMFY_CLI_ARGS="--cpu"

# GPU with low VRAM
COMFY_CLI_ARGS="--lowvram"

# GPU with very low VRAM
COMFY_CLI_ARGS="--novram"

# CPU with optimizations
COMFY_CLI_ARGS="--cpu --force-fp16"

# Custom port (overridden by Docker)
COMFY_CLI_ARGS="--port 8080"

# Verbose logging
COMFY_CLI_ARGS="--verbose"
```

### Docker Compose Profiles
- `comfy` - GPU mode (port 8188)
- `comfy-cpu` - CPU mode (port 8189)

## 🔧 Common Commands

### Service Management
```bash
# Start GPU service
docker compose --profile comfy up -d

# Start CPU service
docker compose --profile comfy-cpu up -d

# Stop all services
docker compose down

# View logs
docker compose logs -f

# Restart service
docker compose restart
```

### Building Images
```bash
# Build GPU image
docker compose --profile comfy build

# Build CPU image
docker compose --profile comfy-cpu build

# Force rebuild (no cache)
docker compose --profile comfy build --no-cache
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

## 🧪 Testing

### Run Tests
```bash
# All tests
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all

# Specific test categories
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner build
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner cpu
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner gpu

# Verbose output
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all --verbose
```

### Test Cleanup
```bash
# Clean test environment
docker compose -f tests/docker-compose.test.yml down --remove-orphans --volumes
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

# Verify GPU support
docker compose --profile comfy exec comfy nvidia-smi
```

#### Permission Issues
```bash
# Fix file permissions
sudo chown -R $USER:$USER ./data ./output

# Check Docker permissions
docker info
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

### Useful Commands
```bash
# Check Docker version
docker --version
docker compose version

# View running containers
docker ps

# Clean up Docker resources
docker system prune -f

# View Docker disk usage
docker system df

# Remove unused images
docker image prune -f
```

## 📁 Directory Structure

```
stable-diffusion-webui-docker/
├── docker-compose.yml          # Main service configuration
├── .env.example               # Environment template
├── .env                       # Your configuration (create from .env.example)
├── services/comfy/            # ComfyUI Docker configuration
├── data/                      # Models, configurations (auto-created)
├── output/                    # Generated images (auto-created)
└── tests/                     # Testing infrastructure
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
4. **Updates**: Pull latest images with `docker compose pull`
5. **Backup**: Regularly backup your `./data/` directory
6. **Performance**: Use GPU mode for best performance, CPU mode for compatibility

## 🆘 Getting Help

1. **Check logs**: `docker compose logs`
2. **Review configuration**: Verify `.env` file settings
3. **Test setup**: Run test suite to validate installation
4. **Search issues**: Check existing GitHub issues
5. **Create issue**: Provide logs and configuration details

For detailed documentation, see:
- [CPU Support Guide](CPU_SUPPORT.md) - Comprehensive GPU/CPU configuration
- [Testing Guide](TESTING_GUIDE.md) - Detailed testing documentation
