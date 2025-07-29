# Scripts Guide

Complete guide to the ComfyUI Docker script system for customizing container setup and bootstrapping.

## Overview

The ComfyUI Docker system includes a powerful script management system that allows you to customize container setup through external scripts. Scripts are organized in categories, executed automatically during startup, and provide colored logging for better visibility.

## Quick Start

### Adding Your First Custom Script

1. **Create a script directory**:
   ```bash
   mkdir -p scripts/custom
   ```

2. **Create your script**:
   ```bash
   cat > scripts/custom/01-my-setup.sh << 'EOF'
   #!/bin/bash
   set -e
   
   # Source logging functions for colored output
   source "$(dirname "$0")/../logging.sh"
   
   log_info "Installing my custom component..."
   
   # Your installation logic here
   pip install my-package
   
   log_success "Custom component installed successfully!"
   EOF
   ```

3. **Make it executable**:
   ```bash
   chmod +x scripts/custom/01-my-setup.sh
   ```

4. **Test it**:
   ```bash
   # Force script re-execution
   docker compose exec comfy rm -f .post_install_done
   docker compose restart && docker compose logs -f
   ```

## Script Organization

### Directory Structure

Scripts are stored in the `scripts/` directory and organized by category:

```
scripts/
├── logging.sh          # Shared logging library
├── base/               # Core setup scripts (executed first)
│   ├── 00-file-structure.sh    # Creates directory structure
│   └── 01-install-comfy-manager.sh  # Installs ComfyUI Manager
├── extended/           # Extended functionality scripts
│   ├── 10-install-ipadapter.sh     # IP Adapter setup
│   ├── 11-install-pulid-flux.sh    # PuLID Flux setup
│   ├── 12-install-tea-cache.sh     # TEA Cache optimization
│   ├── 13-install-hi-diffusion.sh  # Hi-Diffusion setup
│   └── 99-custom-nodes.sh          # Additional custom nodes
└── [your-category]/    # Your custom script categories
    ├── 01-first-script.sh
    ├── 02-second-script.sh
    └── 99-final-script.sh
```

### Execution Order

Scripts execute with predictable ordering:

1. **By Category**: Directories processed alphabetically (`base/` → `extended/` → `your-category/`)
2. **Within Category**: Scripts run numerically/alphabetically (`01-*` → `02-*` → `99-*`)
3. **One-Time Only**: Scripts only run once (unless `.post_install_done` is removed)

## Logging System

### Using Colored Logging

All scripts can use standardized colored logging by sourcing the logging library:

```bash
#!/bin/bash
set -e

# Source logging functions for colored output
source "$(dirname "$0")/../logging.sh"

# Available logging functions
log_info "General information and progress updates"
log_success "Successful operations and completions"
log_warning "Non-critical issues and warnings"
log_error "Critical errors that require attention"
```

### Output Examples

When executed, the logging functions produce:
- 🔵 **[INFO]** Starting component installation...
- 🟢 **[SUCCESS]** Component installed successfully!
- 🟡 **[WARNING]** Using cached version of component
- 🔴 **[ERROR]** Failed to install component

## Script Development

### Script Template

Use this template for new scripts:

```bash
#!/bin/bash
set -e

# Source logging functions for colored output
source "$(dirname "$0")/../logging.sh"

# Script: Brief description of what this script does
# Category: [base|extended|custom|etc]
# Purpose: Detailed explanation of the script's purpose

log_info "Starting [component name] installation..."

# Check if already installed/configured (idempotent check)
if [ -f "/path/to/completion/marker" ]; then
    log_info "[Component] already installed, skipping..."
    exit 0
fi

# Validate prerequisites
if ! command -v required-tool &> /dev/null; then
    log_error "Required tool 'required-tool' not found"
    exit 1
fi

# Main installation logic with error handling
log_info "Downloading [component]..."
if curl -o /tmp/component.tar.gz https://example.com/component.tar.gz; then
    log_success "Download completed"
else
    log_error "Failed to download [component]"
    exit 1
fi

log_info "Installing [component]..."
if tar -xzf /tmp/component.tar.gz -C /target/directory; then
    log_success "[Component] extracted successfully"
else
    log_error "Failed to extract [component]"
    exit 1
fi

# Cleanup temporary files
rm -f /tmp/component.tar.gz

# Create completion marker for idempotency
touch "/path/to/completion/marker"

log_success "[Component] installation completed successfully!"
```

### Best Practices

#### Script Requirements
- **Use `set -e`** - Exit immediately on command failure
- **Source logging library** - For consistent colored output
- **Add header comments** - Document purpose and category
- **Make idempotent** - Safe to run multiple times
- **Handle errors gracefully** - Check command success and provide clear error messages

#### Naming Conventions
- **Numerical prefixes**: `00-99` to control execution order
- **Descriptive names**: `install-component-name.sh`
- **Lowercase with hyphens**: `my-custom-setup.sh`

#### Directory Organization
- **Group by purpose**: Create categories that make sense (`ai-models/`, `performance/`, `custom-nodes/`)
- **Keep focused**: One primary purpose per script
- **Use meaningful names**: Category names should be self-explanatory

## Managing Scripts

### Force Script Re-execution

Scripts only run once by default. To force re-execution:

```bash
# Remove completion marker
docker compose exec comfy rm -f .post_install_done

# Restart container to trigger scripts
docker compose restart

# Monitor execution with logs
docker compose logs -f
```

### Testing Individual Scripts

```bash
# Test script syntax
bash -n scripts/category/script.sh

# Test script execution in container
docker compose exec comfy bash /home/comfy/app/scripts/category/script.sh

# Test with debug output
docker compose exec comfy bash -x /home/comfy/app/scripts/category/script.sh
```

### Script Debugging

#### Common Issues
- **Permission Denied**: Ensure scripts are executable (`chmod +x`)
- **Syntax Errors**: Use `bash -n script.sh` to check syntax
- **Path Issues**: Use absolute paths or verify working directory
- **Missing Dependencies**: Check that required tools are available

#### Debug Commands

```bash
# Check script permissions
docker compose exec comfy ls -la /home/comfy/app/scripts/category/

# Verify script content
docker compose exec comfy cat /home/comfy/app/scripts/category/script.sh

# Check environment variables
docker compose exec comfy env | grep COMFY

# Monitor real-time execution
docker compose logs -f --tail=0
```

## Common Use Cases

### Installing Custom Nodes

```bash
#!/bin/bash
set -e
source "$(dirname "$0")/../logging.sh"

NODE_NAME="ComfyUI-CustomNode"
NODE_REPO="https://github.com/author/ComfyUI-CustomNode.git"
INSTALL_PATH="$COMFY_BASE_DIRECTORY/custom_nodes/$NODE_NAME"

log_info "Installing $NODE_NAME..."

if [ ! -d "$INSTALL_PATH" ]; then
    if git clone --depth 1 "$NODE_REPO" "$INSTALL_PATH"; then
        log_success "$NODE_NAME installed successfully"
    else
        log_error "Failed to install $NODE_NAME"
        exit 1
    fi
else
    log_info "$NODE_NAME already installed"
fi
```

### Installing Python Packages

```bash
#!/bin/bash
set -e
source "$(dirname "$0")/../logging.sh"

PACKAGES=("package1" "package2" "package3")

log_info "Installing Python packages..."

for package in "${PACKAGES[@]}"; do
    log_info "Installing $package..."
    if pip install "$package"; then
        log_success "$package installed successfully"
    else
        log_error "Failed to install $package"
        exit 1
    fi
done

log_success "All Python packages installed successfully"
```

### System Configuration

```bash
#!/bin/bash
set -e
source "$(dirname "$0")/../logging.sh"

CONFIG_FILE="/path/to/config.conf"
BACKUP_FILE="/path/to/config.conf.backup"

log_info "Configuring system settings..."

# Backup existing configuration
if [ -f "$CONFIG_FILE" ]; then
    log_info "Backing up existing configuration..."
    cp "$CONFIG_FILE" "$BACKUP_FILE"
fi

# Apply new configuration
log_info "Applying new configuration..."
cat > "$CONFIG_FILE" << 'EOF'
# Custom configuration
setting1=value1
setting2=value2
EOF

log_success "System configuration completed"
```

### Downloading Models

```bash
#!/bin/bash
set -e
source "$(dirname "$0")/../logging.sh"

MODEL_URL="https://example.com/model.safetensors"
MODEL_PATH="$COMFY_BASE_DIRECTORY/models/checkpoints/model.safetensors"

log_info "Downloading AI model..."

if [ ! -f "$MODEL_PATH" ]; then
    log_info "Model not found, downloading..."
    if curl -L -o "$MODEL_PATH" "$MODEL_URL"; then
        log_success "Model downloaded successfully"
    else
        log_error "Failed to download model"
        exit 1
    fi
else
    log_info "Model already exists, skipping download"
fi
```

## Troubleshooting

### Script Execution Issues

#### Scripts Not Running
1. **Check script permissions**: `ls -la scripts/category/`
2. **Verify executable bit**: `chmod +x scripts/category/*.sh`
3. **Check syntax**: `bash -n scripts/category/script.sh`

#### Scripts Running Multiple Times
1. **Check completion marker**: Look for `.post_install_done` in container
2. **Verify idempotency**: Ensure scripts can safely run multiple times
3. **Add completion checks**: Use conditional logic to skip if already done

#### Logging Not Working
1. **Verify logging library**: Ensure `scripts/logging.sh` exists
2. **Check source path**: Verify the relative path in your script
3. **Test logging library**: `source scripts/logging.sh && log_info "test"`

### Container Issues

#### Permission Problems
```bash
# Fix ownership of scripts
sudo chown -R $USER:$USER scripts/

# Verify container can access scripts
docker compose exec comfy ls -la /home/comfy/app/scripts/
```

#### Environment Variable Issues
```bash
# Check available environment variables
docker compose exec comfy env | grep COMFY

# Verify ComfyUI paths
docker compose exec comfy echo $COMFY_BASE_DIRECTORY
```

### Getting Help

- **Check container logs**: `docker compose logs -f`
- **Test individual scripts**: `docker compose exec comfy bash script.sh`
- **Verify script syntax**: `bash -n script.sh`
- **Search project issues**: [GitHub Issues](https://github.com/pixeloven/ComfyUI-Docker/issues)

---

**[⬆ Back to Documentation](../index.md)** | **[🚀 Quick Start](quick-start.md)** | **[⚙️ Configuration](configuration.md)** 