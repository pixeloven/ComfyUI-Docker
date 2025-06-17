# ComfyUI CPU Support

This document describes how to use ComfyUI in CPU-only mode, which is useful for systems without NVIDIA GPUs or for testing purposes.

## Quick Start

### Using CPU Mode

1. **Copy the environment file:**
   ```bash
   cp .env.example .env
   ```

2. **Configure for CPU mode:**
   Edit `.env` and set:
   ```bash
   COMFY_CLI_ARGS="--cpu"
   ```

3. **Start ComfyUI in CPU mode:**
   ```bash
   docker compose --profile comfy-cpu up -d
   ```

4. **Access ComfyUI:**
   Open http://localhost:8189 in your browser

### Using GPU Mode (Default)

1. **Start ComfyUI in GPU mode:**
   ```bash
   docker compose --profile comfy up -d
   ```

2. **Access ComfyUI:**
   Open http://localhost:8188 in your browser

## Configuration Options

### Environment Variables

The main configuration is done through the `COMFY_CLI_ARGS` environment variable in your `.env` file:

```bash
# For CPU-only mode
COMFY_CLI_ARGS="--cpu"

# For CPU with forced FP16 (may improve performance)
COMFY_CLI_ARGS="--cpu --force-fp16"

# For GPU with low VRAM
COMFY_CLI_ARGS="--lowvram"

# For GPU with very low VRAM
COMFY_CLI_ARGS="--novram"

# Multiple options can be combined
COMFY_CLI_ARGS="--cpu --force-fp16 --verbose"
```

### Docker Compose Profiles

Two profiles are available:

- `comfy` - GPU mode (default, uses port 8188)
- `comfy-cpu` - CPU mode (uses port 8189)

### Port Configuration

- **GPU mode**: http://localhost:8188
- **CPU mode**: http://localhost:8189

Different ports allow running both modes simultaneously for testing.

## Performance Considerations

### CPU Mode Performance

- **Slower than GPU**: CPU inference is significantly slower than GPU
- **Memory usage**: CPU mode uses system RAM instead of VRAM
- **Model compatibility**: All models should work, but performance varies
- **Optimization**: Use `--force-fp16` for potential speed improvements

### Recommended CPU Configurations

```bash
# Basic CPU mode
COMFY_CLI_ARGS="--cpu"

# Optimized CPU mode
COMFY_CLI_ARGS="--cpu --force-fp16"

# CPU mode with verbose logging
COMFY_CLI_ARGS="--cpu --verbose"
```

### GPU Mode Optimizations

```bash
# For GPUs with 4-6GB VRAM
COMFY_CLI_ARGS="--lowvram"

# For GPUs with <4GB VRAM
COMFY_CLI_ARGS="--novram"

# For high-end GPUs (default)
COMFY_CLI_ARGS=""
```

## Docker Images

A single unified image is built that works for both GPU and CPU:

- `comfy:v0.3.39` - Uses onnxruntime-gpu which automatically falls back to CPU when CUDA is unavailable

### Simplified Single-Stage Build

The Dockerfile uses a single stage with onnxruntime-gpu that automatically handles both GPU and CPU:

```dockerfile
# Single unified image
FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

# Install onnxruntime-gpu which automatically falls back to CPU
RUN pip install onnxruntime-gpu
```

Build command:

```bash
# Build unified image (works for both GPU and CPU)
docker build -t comfy:v0.3.39 ./services/comfy
```

**Key Benefits**:
- **Automatic fallback**: onnxruntime-gpu automatically uses CPU when CUDA is unavailable
- **Simplified maintenance**: Single image to build and maintain
- **Reduced complexity**: No need for separate build targets or conditional logic
- **Better caching**: Single build path improves Docker layer caching

## Docker Compose Commands

Use Docker Compose directly for all operations:

```bash
# Build both images
docker compose --profile comfy build
docker compose --profile comfy-cpu build

# Start GPU mode
docker compose --profile comfy up -d

# Start CPU mode
docker compose --profile comfy-cpu up -d

# Stop all services
docker compose down --remove-orphans

# View logs
docker compose logs -f
```

## Testing

### Running Tests

```bash
# Run all tests using containerized testing
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all

# Test CPU mode only
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner cpu

# Test GPU mode only (requires NVIDIA GPU)
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner gpu

# Alternative: Direct Python runner (for development)
python3 tests/test_runner.py all
python3 tests/test_runner.py cpu

# Test Docker builds
./scripts/test.sh build
```

### Test Requirements

Tests require:
- Docker and docker-compose
- Python 3.7+
- pytest and dependencies (installed automatically)

## Troubleshooting

### Common Issues

1. **Port conflicts**: If port 8188 or 8189 is in use, modify the ports in `docker-compose.yml`

2. **Memory issues in CPU mode**: Reduce model size or increase system RAM

3. **Slow performance in CPU mode**: This is expected; consider using smaller models

4. **GPU not detected**: Ensure NVIDIA drivers and Docker GPU support are installed

### Logs

View logs for debugging:

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f comfy
docker compose logs -f comfy-cpu
```

### Container Shell Access

Access container for debugging:

```bash
# GPU container
make shell-gpu

# CPU container  
make shell-cpu
```

## Advanced Configuration

### Custom CLI Arguments

ComfyUI supports many CLI arguments. Common ones include:

- `--cpu` - Force CPU mode
- `--force-fp16` - Force FP16 precision
- `--lowvram` - Low VRAM mode
- `--novram` - No VRAM mode (use system RAM)
- `--verbose` - Verbose logging
- `--port` - Custom port (overridden by Docker)

### Volume Mounts

Both modes share the same data volumes:
- `./data:/data` - Models, configurations, cache
- `./output:/output` - Generated images and outputs

### Environment Variables

Additional environment variables:
- `PUID`/`PGID` - User/group IDs for file permissions
- `CLI_ARGS` - Passed to ComfyUI (set via COMFY_CLI_ARGS)

## Migration from GPU to CPU

To switch an existing GPU setup to CPU:

1. Update `.env`:
   ```bash
   COMFY_CLI_ARGS="--cpu"
   ```

2. Stop GPU service:
   ```bash
   docker compose --profile comfy down
   ```

3. Start CPU service:
   ```bash
   docker compose --profile comfy-cpu up -d
   ```

4. Access on new port: http://localhost:8189

All data and models will be preserved as they use the same volumes.
