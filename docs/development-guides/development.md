# Development

Development setup and contributing to ComfyUI Docker.

## Setup

```bash
# Clone and setup
git clone https://github.com/pixeloven/ComfyUI-Docker.git
cd ComfyUI-Docker

# Create .env file with default settings
cat > .env << EOF
# User/Group IDs for container permissions
PUID=1000
PGID=1000

# ComfyUI Configuration
COMFY_PORT=8188
CLI_ARGS=

# Performance Configuration
CLI_ARGS=
EOF
```

## Environment Variables

The application supports the following environment variables:

### User Configuration
- `PUID` (default: 1000) - User ID for container permissions
- `PGID` (default: 1000) - Group ID for container permissions

### ComfyUI Configuration
- `COMFY_PORT` (default: 8188) - Port for ComfyUI web interface
- `CLI_ARGS` (default: "") - Additional CLI arguments for ComfyUI
  - `--cpu` - Force CPU-only mode
  - `--lowvram` - Low VRAM mode for 4-6GB GPUs
  - `--novram` - No VRAM mode

### Performance Configuration
- `CLI_ARGS` (default: "") - Additional CLI arguments for ComfyUI performance tuning

### Build Configuration
- `REGISTRY_URL` (default: "ghcr.io/pixeloven/comfyui-docker/") - Docker registry URL
- `IMAGE_LABEL` (default: "latest") - Image tag
- `RUNTIME` (default: "nvidia") - Runtime type
- `PLATFORMS` (default: ["linux/amd64"]) - Target platforms

## Building Images

This project uses Docker Bake for building images with support for multiple runtimes and efficient caching.

### Prerequisites

```bash
# Ensure Docker Buildx is available
docker buildx version

# Create a new builder instance if needed
docker buildx create --name mybuilder --use
```

### Quick Build Commands

```bash
# Build all images (NVIDIA and CPU runtimes)
docker buildx bake all

# Build only NVIDIA runtime and application
docker buildx bake nvidia

# Build only CPU runtime and application
docker buildx bake cpu

# Build specific target
docker buildx bake comfy-nvidia
docker buildx bake comfy-cpu
```

### Available Targets

#### Runtime Images
- `runtime-nvidia` - Base NVIDIA CUDA runtime with cuDNN
- `runtime-cpu` - Base CPU runtime (Ubuntu 24.04)

#### Application Images
- `comfy-nvidia` - ComfyUI with NVIDIA GPU support
- `comfy-cpu` - ComfyUI with CPU-only support

#### Convenience Groups
- `all` - Build all images (runtimes + applications)
- `runtime` - Build both runtime base images
- `comfy` - Build both ComfyUI application images
- `nvidia` - Build NVIDIA runtime and application
- `cpu` - Build CPU runtime and application

### Custom Build Options

```bash
# Build with custom registry
docker buildx bake all --set "*.args.REGISTRY_URL=myregistry.com/myuser"

# Build with custom image label
docker buildx bake all --set "*.args.IMAGE_LABEL=v1.0.0"

# Build for multiple platforms
docker buildx bake all --set "*.platforms=linux/amd64,linux/arm64"

# Build without cache (force rebuild)
docker buildx bake all --no-cache

# Build with verbose output
docker buildx bake all --progress=plain
```

### Troubleshooting Builds

```bash
# Check build context
docker buildx bake --print

# Debug specific target
docker buildx bake comfy-nvidia --progress=plain

# Clear build cache
docker buildx prune -a

# Check available builders
docker buildx ls
```

## Test Workflow

```bash
# Start development environment
docker compose --profile comfy-nvidia up -d

# Monitor logs
docker compose logs -f

# Test changes
docker compose restart
```

## Testing

### Local Testing
```bash
# Test GPU service
docker compose --profile comfy-nvidia up -d
curl -f http://localhost:8188

# Test CPU service
docker compose down
docker compose --profile comfy-cpu up -d
curl -f http://localhost:8188
```

## Contributing

### Before Contributing
1. Create a discussion describing the problem and solution
2. Fork the repository and create a feature branch
3. Test your changes locally
4. Open a pull request

### Guidelines
- Follow existing code style and patterns
- Update documentation if needed
- Keep commits focused and descriptive

## Script Development

ComfyUI Docker uses a modular script system for container bootstrapping and setup. Scripts are mounted as volumes and executed during container startup with sophisticated logging and error handling.

### Script System Architecture

The script system consists of:

- **Script Directory Structure**: `scripts/category/*.sh` (one level deep)
- **Startup Script**: `services/comfy/base/startup.sh` with enhanced logging
- **Volume Mounting**: Scripts mounted read-only to `/home/comfy/app/scripts`
- **Execution Engine**: Function-based execution with colored logging

### Logging Functions

The startup script provides standardized logging functions with colors:

```bash
# Available logging functions
log_info "Informational message"     # Blue [INFO]
log_success "Success message"        # Green [SUCCESS]  
log_warning "Warning message"        # Yellow [WARNING]
log_error "Error message"            # Red [ERROR]

# Color codes (if you need custom logging)
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color
```

### Script Categories

#### Base Scripts (`scripts/base/`)
Core functionality scripts that run first:
- `00-file-structure.sh` - Creates essential directory structure
- `01-install-comfy-manager.sh` - Installs ComfyUI Manager

#### Extended Scripts (`scripts/extended/`)
Additional functionality for the extended image:
- `10-install-ipadapter.sh` - IP Adapter integration
- `11-install-pulid-flux.sh` - PuLID Flux setup
- `12-install-tea-cache.sh` - TEA Cache optimization
- `13-install-hi-diffusion.sh` - Hi-Diffusion setup
- `99-custom-nodes.sh` - Additional custom nodes

### Creating New Scripts

#### 1. Script Structure Template

```bash
#!/bin/bash
set -e

# Script: [Brief description]
# Category: [base|extended|custom]
# Purpose: [Detailed purpose]

echo "Starting [script name]..."

# Check if already installed/configured
if [ -f "/some/marker/file" ]; then
    echo "Already configured, skipping..."
    exit 0
fi

# Main installation logic
echo "Installing [component]..."
# ... installation commands ...

# Create completion marker
touch "/some/marker/file"
echo "Successfully installed [component]"
```

#### 2. Script Naming Convention

- Use numerical prefixes: `00-99`
- Descriptive names: `10-install-component.sh`
- Lower case with hyphens: `component-name.sh`

#### 3. Best Practices

- **Idempotent**: Safe to run multiple times
- **Error Handling**: Use `set -e` and check command success
- **Logging**: Use echo statements for user feedback
- **Dependencies**: Check for required tools/packages before use
- **Cleanup**: Clean up temporary files and caches

### Testing Scripts

#### Local Testing

```bash
# Test script syntax
bash -n scripts/category/script.sh

# Test script execution in container
docker compose exec comfy bash /home/comfy/app/scripts/category/script.sh

# Test with debug output
docker compose exec comfy bash -x /home/comfy/app/scripts/category/script.sh
```

#### Integration Testing

```bash
# Force script re-execution
docker compose exec comfy rm -f .post_install_done

# Restart container and monitor logs
docker compose restart && docker compose logs -f
```

#### Testing New Categories

```bash
# Create test category
mkdir -p scripts/test
echo '#!/bin/bash
set -e
echo "Test script executed successfully"' > scripts/test/01-test.sh
chmod +x scripts/test/01-test.sh

# Test execution
docker compose exec comfy rm -f .post_install_done
docker compose restart
```

### Script Execution Flow

The startup script executes scripts in this order:

1. **Check Status**: Verify if post-install is complete
2. **Process Categories**: Loop through `scripts/*/` in alphabetical order
3. **Execute Scripts**: Run all `*.sh` files in each category
4. **Log Results**: Track success/failure with colored output
5. **Mark Complete**: Create `.post_install_done` marker

### Debugging Script Issues

#### Common Issues

- **Permission Denied**: Ensure scripts are executable (`chmod +x`)
- **Syntax Errors**: Use `bash -n script.sh` to check syntax
- **Path Issues**: Use absolute paths or verify working directory
- **Environment**: Scripts run in the ComfyUI virtual environment

#### Debug Commands

```bash
# Check script permissions
docker compose exec comfy ls -la /home/comfy/app/scripts/

# Verify script content
docker compose exec comfy cat /home/comfy/app/scripts/category/script.sh

# Check execution environment
docker compose exec comfy env

# Monitor real-time execution
docker compose logs -f --tail=0
```

### Modifying the Startup Script

If you need to modify the script execution logic in `services/comfy/base/startup.sh`:

#### Key Functions

- `run_post_install_scripts()` - Main execution function
- `check_post_install_status()` - Status checking
- `mark_post_install_complete()` - Completion marking
- `log_*()` functions - Logging utilities

#### Testing Startup Changes

```bash
# Test syntax
bash -n services/comfy/base/startup.sh

# Build and test
docker buildx bake comfy-cuda
docker compose up -d && docker compose logs -f
```

