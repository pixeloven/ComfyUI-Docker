# Documentation

Guides for ComfyUI Docker setup, usage, and development.

## 📖 User Guides

### [Getting Started](GETTING_STARTED.md)
Quick setup and first run guide.
- One-command setup
- Hardware mode selection
- Basic configuration
- Next steps

### [Usage Guide](USAGE.md)
Daily operations and workflows.
- Essential commands
- Model management
- Configuration options
- Common workflows

### [Configuration](CONFIGURATION.md)
Environment variables and advanced settings.
- Environment variables reference
- Hardware configuration
- Performance tuning
- Security settings

### [Troubleshooting](TROUBLESHOOTING.md)
Common issues and solutions.
- Critical issues
- Performance problems
- Diagnostic commands
- Getting help

## 🛠️ Developer Guides

### [Build Guide](BUILD.md)
Development setup and contributing.
- Building images
- Development workflow
- Testing procedures
- Contribution guidelines

### [Local Testing](LOCAL_TESTING.md)
Test CI workflows locally.
- Quick setup
- Common commands
- Troubleshooting

## 🚀 Quick Start

```bash
# 1. Clone and setup
git clone https://github.com/pixeloven/ComfyUI-Docker.git
cd ComfyUI-Docker
cp .env.example .env

# 2. Start ComfyUI
docker compose --profile comfy up -d        # GPU mode
# OR
docker compose --profile comfy-cpu up -d    # CPU mode

# 3. Open http://localhost:8188
```

## 📋 Service Profiles

- **`comfy`** - GPU-accelerated ComfyUI
- **`comfy-cpu`** - CPU-only ComfyUI  
- **`comfy-setup`** - Model download utility

---

**[⬆ Back to Main README](../README.md)** | **[🐛 Report Issues](https://github.com/pixeloven/ComfyUI-Docker/issues)**
