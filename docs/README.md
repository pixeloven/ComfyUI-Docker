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

## 🚀 Quick Start

New to this project? Start here:

1. **[Quick Reference](QUICK_REFERENCE.md)** - Get up and running in minutes
2. **[CPU Support Guide](CPU_SUPPORT.md)** - Configure for your hardware

## 🎯 Common Tasks

### First Time Setup
```bash
# Clone and start
git clone <repo-url>
cd stable-diffusion-webui-docker
cp .env.example .env
docker compose --profile comfy up -d
# Visit http://localhost:8188
```

### Testing Your Setup
```bash
# Run all tests
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all
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
