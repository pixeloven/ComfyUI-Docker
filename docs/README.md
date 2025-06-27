# Documentation Index

Comprehensive guides for ComfyUI Docker setup, usage, and development.

## 📖 User Guides

### [Quick Reference](QUICK_REFERENCE.md)
Essential commands, configuration, and troubleshooting for daily use.
- Getting started commands
- Configuration options
- Common troubleshooting
- Useful tips and tricks

### [CPU Support Guide](CPU_SUPPORT.md)
GPU vs CPU configuration and performance optimization.
- Hardware requirements
- Performance considerations
- Configuration examples
- Mode switching

## 🛠️ Developer Guides

### [Build Guide](BUILD.md)
Building Docker images, development setup, and contributing.
- Building and customizing images
- Development workflow
- Testing procedures
- Contribution guidelines

### [Local CI Testing](LOCAL_CI_TESTING.md)
Test GitHub Actions workflows locally using act.
- Local testing setup
- Common commands
- Troubleshooting CI issues

## 🚀 Getting Started

**New users**: Start with [Quick Reference](QUICK_REFERENCE.md) for immediate setup.

**Developers**: See [Build Guide](BUILD.md) for development environment setup.

## 📋 Quick Reference

### Docker Services
- **`comfy`** - Main ComfyUI interface (port 8188)
- **`comfy-setup`** - Model download utility

### Essential Commands
```bash
# Start ComfyUI
docker compose --profile comfy up -d

# Download models
docker compose --profile comfy-setup up

# View logs
docker compose logs -f
```

### Getting Help
1. Check [Quick Reference](QUICK_REFERENCE.md) for detailed commands
2. Review service logs: `docker compose logs -f`
3. Search [GitHub issues](https://github.com/AbdBarho/stable-diffusion-webui-docker/issues)
4. Create new issue with logs and configuration

---

**[⬆ Back to Main README](../README.md)** | **[🐛 Report Issues](https://github.com/AbdBarho/stable-diffusion-webui-docker/issues)**
