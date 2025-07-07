# Documentation

Guides for ComfyUI Docker setup, usage, and development.

## �� User Guides

### [Quick Start](QUICK_START.md)
Get running in 5 minutes.
- One-command setup
- Hardware mode selection
- Basic configuration
- First steps

### [Usage Guide](USAGE.md)
Daily operations and workflows.
- Essential commands
- Model management
- Configuration options
- Common workflows
- Troubleshooting

## 🛠️ Developer Guides

### [Development](DEVELOPMENT.md)
Development setup and contributing.
- Building images with Docker Bake
- Development workflow
- Testing procedures
- Contribution guidelines

### [CI/CD](CI_CD.md)
Docker Bake workflows and local testing.
- Workflow overview
- Local testing with Act
- Docker Bake groups and targets
- Best practices

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

## 🔧 Docker Bake Groups

- **`all`** - All images (runtime-nvidia, runtime-cpu, comfy-nvidia, comfy-cpu, comfy-setup)
- **`runtime`** - Runtime images only
- **`nvidia`** - NVIDIA images (runtime-nvidia, comfy-nvidia)
- **`cpu`** - CPU images (runtime-cpu, comfy-cpu)
- **`comfy`** - ComfyUI images (comfy-nvidia, comfy-cpu)

---

**[⬆ Back to Main README](../README.md)** | **[🐛 Report Issues](https://github.com/pixeloven/ComfyUI-Docker/issues)**
