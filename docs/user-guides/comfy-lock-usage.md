# Using comfy-lock.yaml for Custom Nodes and Models

This guide explains how to use the `comfy-lock.yaml` file to manage custom nodes and models in your ComfyUI Docker project.

## Overview

The `comfy-lock.yaml` file allows you to:
- Define and version-control custom node installations
- Manage model downloads and organization
- Ensure consistent environments across deployments

## File Location

```
services/comfy/comfy-lock.yaml
```

## Current Configuration

Your current `comfy-lock.yaml` includes:

### Basic Settings
- **Workspace**: `/home/ubuntu/app` (Docker container path)
- **ComfyUI Version**: `v0.3.43`

### Custom Nodes
- **ComfyUI-Manager**: Enabled and installed automatically

## Accessing the CLI

```bash
# Enter the running container
docker compose exec comfy bash

# Or run commands directly
docker compose exec comfy comfy --help
```

## Managing Custom Nodes

### Method 1: Edit comfy-lock.yaml Directly

1. Open `services/comfy/comfy-lock.yaml`
2. Add your custom node under the `git_custom_nodes` section:

```yaml
git_custom_nodes:
  "https://github.com/ltdrdata/ComfyUI-Manager":
    disabled: false
    hash: "latest"
  
  # Add your custom node here
  "https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved":
    disabled: false
    hash: "latest"
```

### Method 2: Use ComfyUI CLI

```bash
# Install a custom node
comfy node install ComfyUI-AnimateDiff-Evolved

# Save the current state to comfy-lock.yaml
comfy node save-snapshot
```

### Popular Custom Nodes

#### Animation
- **ComfyUI-AnimateDiff-Evolved**: `https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved`

#### ControlNet
- **ComfyUI-Impact-Pack**: `https://github.com/ltdrdata/ComfyUI-Impact-Pack`
- **ComfyUI-ControlNet-Aux**: `https://github.com/Fannovel16/comfyui_controlnet_aux`

#### Upscaling
- **ComfyUI-Ultimate-SD-Upscale**: `https://github.com/ssitu/ComfyUI-Ultimate-SD-Upscale`

### Node Management Commands

```bash
# Install nodes
comfy node install ComfyUI-AnimateDiff-Evolved ComfyUI-Impact-Pack

# List nodes
comfy node show installed
comfy node show enabled

# Update nodes
comfy node update all
comfy node update ComfyUI-Manager

# Enable/disable nodes
comfy node enable ComfyUI-AnimateDiff-Evolved
comfy node disable ComfyUI-AnimateDiff-Evolved
```

## Managing Models

### Add Models to comfy-lock.yaml

```yaml
models:
  - model: "stable-diffusion-v1-5"
    url: "https://huggingface.co/runwayml/stable-diffusion-v1-5/resolve/main/v1-5-pruned.safetensors"
    paths:
      - path: "models/checkpoints"
    hashes:
      - hash: "your-hash-here"
        type: "SHA256"
    type: "checkpoint"
```

### Download Models via CLI

```bash
# Download from Hugging Face
comfy model download --url https://huggingface.co/runwayml/stable-diffusion-v1-5/resolve/main/v1-5-pruned.safetensors

# Download from CivitAI
comfy model download --url https://civitai.com/api/download/models/123456 --relative-path models/checkpoints

# Download with CivitAI API token
comfy model download --url https://civitai.com/api/download/models/123456 --set-civitai-api-token YOUR_TOKEN

# List models
comfy model list
comfy model list --relative-path models/loras

# Remove models
comfy model remove --model-names "model1.safetensors,model2.ckpt"
```

## Using comfy-lock.yaml

### Install from comfy-lock.yaml

```bash
# Install all custom nodes and models defined in comfy-lock.yaml
comfy node install-deps --deps=comfy-lock.yaml
```

### Generate from Workflow

```bash
# Generate comfy-lock.yaml from a workflow file
comfy node deps-in-workflow --workflow=workflow.json --output=comfy-lock.yaml
```

### Save Current State

```bash
# Save current custom node state to comfy-lock.yaml
comfy node save-snapshot
```

## Version Control

### Use Specific Commit Hashes

For reproducible builds, use specific commit hashes instead of "latest":

```yaml
git_custom_nodes:
  "https://github.com/ltdrdata/ComfyUI-Manager":
    disabled: false
    hash: "a1b2c3d4e5f6..."  # Specific commit hash
```

### Getting Commit Hashes

1. Visit the GitHub repository
2. Go to the commit history
3. Copy the commit hash you want to use

### Disabling Custom Nodes

To temporarily disable a custom node without removing it:

```yaml
git_custom_nodes:
  "https://github.com/username/custom-node-repo":
    disabled: true  # Set to true to disable
    hash: "latest"
```

## Common Workflows

### Set Up New Custom Nodes

```bash
# 1. Enter container
docker compose exec comfy bash

# 2. Install nodes
comfy node install ComfyUI-AnimateDiff-Evolved ComfyUI-Impact-Pack

# 3. Save configuration
comfy node save-snapshot
```

### Reproduce Environment

```bash
# 1. Copy comfy-lock.yaml to new environment
cp comfy-lock.yaml /path/to/new-environment/

# 2. Install all dependencies
comfy node install-deps --deps=comfy-lock.yaml
```

### Update from Workflow

```bash
# 1. Generate comfy-lock.yaml from workflow
comfy node deps-in-workflow --workflow=workflow.json --output=comfy-lock.yaml

# 2. Install dependencies
comfy node install-deps --deps=comfy-lock.yaml
```

## Troubleshooting

### Custom Node Conflicts

```bash
# Use bisect to identify problematic nodes
comfy node bisect start
comfy node bisect good  # or bad
comfy node bisect reset
```

### Environment Information

```bash
# Show environment
comfy env

# Check tracking
comfy tracking status
comfy tracking disable
```

### Common Issues

1. Verify repository URLs are correct
2. Check if repositories are accessible
3. Ensure commit hashes exist
4. Verify network connectivity in the Docker container

## Best Practices

1. **Use Specific Versions**: Use commit hashes instead of "latest" for production
2. **Test Changes**: Test custom node combinations before committing
3. **Document Changes**: Update this documentation when adding new nodes
4. **Version Control**: Always commit your `comfy-lock.yaml` file

## Quick Reference

### Essential Commands
```bash
# Install from comfy-lock.yaml
comfy node install-deps --deps=comfy-lock.yaml

# Save current state
comfy node save-snapshot

# Generate from workflow
comfy node deps-in-workflow --workflow=workflow.json --output=comfy-lock.yaml

# Install nodes
comfy node install ComfyUI-AnimateDiff-Evolved

# Download models
comfy model download --url <model-url>

# List installed nodes
comfy node show installed

# List models
comfy model list
```

## Related Documentation

- [ComfyUI CLI Documentation](https://comfyui-wiki.com/en/install/install-comfyui/comfy-cli)
- [ComfyUI-Manager Documentation](https://github.com/ltdrdata/ComfyUI-Manager) 