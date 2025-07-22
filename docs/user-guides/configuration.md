# Configuration

Complete guide to configuring ComfyUI Docker.

## Environment Variables

All configuration is handled through environment variables in the `.env` file.

### User Configuration

Control container permissions and user/group IDs:

```bash
# User and group IDs for container permissions
PUID=1000    # User ID (default: 1000)
PGID=1000    # Group ID (default: 1000)
```

**Note**: These should match your host user/group IDs to avoid permission issues.

### ComfyUI Configuration

Control ComfyUI behavior and performance:

```bash
# Web interface port
COMFY_PORT=8188    # Port for ComfyUI web interface (default: 8188)

# Additional CLI arguments
CLI_ARGS=          # Additional arguments passed to ComfyUI
```

#### Available CLI Arguments

- `--cpu` - Force CPU-only mode (useful for systems without GPU)
- `--lowvram` - Low VRAM mode for GPUs with 4-6GB memory
- `--novram` - No VRAM mode (uses system RAM instead)
- `--listen` - Listen on all interfaces (not just localhost)
- `--port 8080` - Override port (alternative to COMFY_PORT)

#### Performance Tuning Examples

```bash
# For 4-6GB GPUs
CLI_ARGS=--lowvram

# For CPU-only systems
CLI_ARGS=--cpu

# For systems with very limited VRAM
CLI_ARGS=--novram

# For remote access
CLI_ARGS=--listen
```

### Performance Configuration

Control ComfyUI performance and resource usage:

```bash
# Additional CLI arguments for performance tuning
CLI_ARGS=          # Additional arguments passed to ComfyUI
```

**Note**: Use CLI_ARGS to optimize performance for your hardware configuration.

## File Structure

The application uses the following directory structure:

```
ComfyUI-Docker/
├── data/                    # Persistent data storage
│   ├── models/             # Downloaded AI models
│   │   ├── Stable-diffusion/  # Checkpoint models
│   │   ├── VAE/              # VAE models
│   │   ├── ControlNet/       # ControlNet models
│   │   └── ...               # Other model types
│   └── config/             # ComfyUI configuration
│       └── comfy/          # ComfyUI settings and custom nodes
├── output/                 # Generated images and outputs
└── .env                    # Environment configuration
```

## Model Management

Model management is now handled through custom nodes within ComfyUI. The comfy-setup service has been deprecated in favor of integrated model management.

### Manual Model Management

You can manually manage models:

1. **Download models** to `./data/models/`
2. **Organize by type** (Stable-diffusion, VAE, ControlNet, etc.)
3. **Use ComfyUI Manager** (automatically installed) for easy model management

## Multi-Instance Configuration

To run multiple ComfyUI instances:

1. **Create separate directories** for each instance
2. **Use different ports** for each instance
3. **Use different data directories** to avoid conflicts

Example for second instance:

```bash
# Create second instance directory
mkdir comfyui-instance-2
cd comfyui-instance-2

# Copy docker-compose.yml and create .env
cp ../docker-compose.yml .
cat > .env << EOF
PUID=1000
PGID=1000
COMFY_PORT=8189
CLI_ARGS=
EOF

# Start second instance
docker compose --profile comfy-nvidia up -d
```

## Troubleshooting Configuration

### Common Issues

1. **Permission Errors**
   ```bash
   # Fix ownership
   sudo chown -R $USER:$USER ./data ./output
   ```

2. **Port Already in Use**
   ```bash
   # Change port in .env
   sed -i 's/COMFY_PORT=8188/COMFY_PORT=8189/' .env
   ```

3. **GPU Not Detected**
   ```bash
   # Test GPU access
   docker run --rm --gpus all nvidia/cuda:11.8-base-ubuntu20.04 nvidia-smi
   ```

4. **Low Memory Errors**
   ```bash
   # Enable low VRAM mode
   sed -i 's/CLI_ARGS=/CLI_ARGS=--lowvram/' .env
   ```

### Validation

Test your configuration:

```bash
# Check environment variables
docker compose config

# Test container startup
docker compose --profile comfy-nvidia up --abort-on-container-exit

# Check logs
docker compose logs -f
```

---

**[⬆ Back to User Guides](index.md)** | **[🚀 Quick Start](quick-start.md)** | **[📖 Usage Guide](usage.md)** 