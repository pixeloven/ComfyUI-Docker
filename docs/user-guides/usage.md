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

The ComfyUI Docker system includes a powerful script management system that allows you to customize the container setup through external scripts. Scripts are organized in categories and executed automatically during container startup.

### Script Organization

Scripts are stored in the `scripts/` directory and organized by category:

```
scripts/
├── base/           # Core setup scripts (always executed first)
│   ├── 00-file-structure.sh    # Creates directory structure
│   └── 01-install-comfy-manager.sh  # Installs ComfyUI Manager
├── extended/       # Extended functionality scripts
│   ├── 10-install-ipadapter.sh     # IP Adapter setup
│   ├── 11-install-pulid-flux.sh    # PuLID Flux setup
│   ├── 12-install-tea-cache.sh     # TEA Cache optimization
│   ├── 13-install-hi-diffusion.sh  # Hi-Diffusion setup
│   └── 99-custom-nodes.sh          # Additional custom nodes
└── [custom]/       # Your custom script categories
    └── *.sh
```

### Script Execution

Scripts are executed with enhanced logging and error handling:

- **Categorized**: Scripts run by directory in alphabetical order (`base/` → `extended/` → etc.)
- **Ordered**: Within each category, scripts run in numerical/alphabetical order
- **Logged**: Each script execution is tracked with colored output:
  - 🔵 **[INFO]** - General information and progress
  - 🟢 **[SUCCESS]** - Successful operations
  - 🟡 **[WARNING]** - Non-critical issues
  - 🔴 **[ERROR]** - Critical errors that stop execution
- **Protected**: Scripts only run once (unless `.post_install_done` is removed)

### Adding Custom Scripts

1. **Create a category directory**:
   ```bash
   mkdir -p scripts/custom
   ```

2. **Add your script**:
   ```bash
   cat > scripts/custom/01-my-setup.sh << 'EOF'
   #!/bin/bash
   set -e
   
   # Your custom setup logic here
   echo "Installing custom dependencies..."
   pip install my-custom-package
   EOF
   ```

3. **Make it executable**:
   ```bash
   chmod +x scripts/custom/01-my-setup.sh
   ```

4. **Restart the container**:
   ```bash
   # Force script re-execution by removing completion marker
   docker compose exec comfy rm -f .post_install_done
   docker compose restart
   ```

### Script Development Guidelines

When creating scripts, follow these best practices:

- **Use `set -e`** at the top to exit on errors
- **Add descriptive echo statements** for user feedback
- **Check for existing installations** to avoid conflicts
- **Use numerical prefixes** (00-99) to control execution order
- **Make scripts idempotent** (safe to run multiple times)

### Troubleshooting Scripts

If a script fails during execution:

1. **Check the logs**:
   ```bash
   docker compose logs -f
   ```

2. **Reset script execution** (forces re-run):
   ```bash
   docker compose exec comfy rm -f .post_install_done
   docker compose restart
   ```

3. **Test individual scripts**:
   ```bash
   docker compose exec comfy bash -x /home/comfy/app/scripts/category/script.sh
   ```

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
