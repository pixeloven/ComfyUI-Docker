# Documentation

Simple guides to get you started with ComfyUI Docker.

## 📚 Available Guides

### [Quick Reference](QUICK_REFERENCE.md)
Essential commands, configuration, and troubleshooting for daily use.

**What's included:**
- Getting started commands
- Configuration options
- Common troubleshooting
- Useful tips and tricks

### [CPU Support Guide](CPU_SUPPORT.md)
How to configure ComfyUI for GPU and CPU modes.

**What's included:**
- GPU vs CPU setup
- Performance considerations
- Configuration examples
- Mode switching

### [Local CI Testing Guide](LOCAL_CI_TESTING.md)
Test GitHub Actions workflows locally using act.

**What's included:**
- Local act installation
- Common commands for this project
- Basic troubleshooting

## 🚀 Quick Start

New to this project? Start here:

1. **[Quick Reference](QUICK_REFERENCE.md)** - Get up and running in minutes
2. **[CPU Support Guide](CPU_SUPPORT.md)** - Configure for your hardware
3. **[Local CI Testing Guide](LOCAL_CI_TESTING.md)** - Test changes locally

## 🏗️ Available Services

This project provides three main Docker services:

### ComfyUI
- **Profile**: `comfy`
- **Port**: 8188
- **Purpose**: Main ComfyUI interface with GPU acceleration
- **Requirements**: NVIDIA GPU with CUDA support

### Model Setup Service
- **Profile**: `comfy-setup`
- **Port**: None (utility service)
- **Purpose**: Download and organize models
- **Usage**: Run once to set up models

## 🎯 Common Tasks

### First Time Setup
```bash
# Clone and start
git clone https://github.com/AbdBarho/stable-diffusion-webui-docker.git
cd stable-diffusion-webui-docker
cp .env.example .env
docker compose build
docker compose --profile comfy-setup up -d
docker compose --profile comfy up -d
# Visit http://localhost:8188
```

### Testing CI Changes Locally
```bash
# Install act locally
curl https://raw.githubusercontent.com/nektos/act/master/install.sh | bash

# Test CI workflow
./bin/act push -W .github/workflows/ci.yml

# Test release workflow
./bin/act push -W .github/workflows/release.yml
```

### Getting Help
1. Check [Quick Reference](QUICK_REFERENCE.md) for common solutions
2. Review logs: `docker compose logs -f`
3. Search existing GitHub issues
4. Create a new issue with logs and configuration

## 💡 Tips for New Users

- **Start with GPU mode** if you have an NVIDIA GPU
- **Use CPU mode** for compatibility on any system
- **Check the logs** if something isn't working
- **Backup your data** directory regularly
- **Update regularly** with `docker compose pull`

---

*Keep it simple, keep it working!*
