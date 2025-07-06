# Usage

Daily operations for ComfyUI Docker.

## Daily Commands

```bash
# Start (GPU)
docker compose --profile comfy up -d
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
docker compose --profile comfy up -d
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

## Configuration

```bash
# Custom port
echo 'COMFY_PORT=8080' >> .env

# Performance tuning
echo 'CLI_ARGS=--lowvram' >> .env    # 4-6GB GPUs
echo 'CLI_ARGS=--novram' >> .env     # CPU fallback
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