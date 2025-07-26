# ComfyUI Docker

A Docker-based setup for running [ComfyUI](https://github.com/comfyanonymous/ComfyUI), a powerful and modular stable diffusion GUI and backend.

## About This Project

ComfyUI Docker provides a **production-ready, containerized solution** for running ComfyUI - the powerful node-based Stable Diffusion interface. Our goal is to eliminate the complexity of AI image generation setup while maintaining the flexibility and power that advanced users need.

### Why ComfyUI Docker?
- **🚀 One-Command Setup** - Get running in minutes, not hours
- **🏗️ Production Ready** - Proper permissions, persistent storage, and error handling
- **🔄 Flexible Deployment** - GPU acceleration or CPU-only modes
- **📦 Model Management** - Automated downloading with verification
- **🔧 Developer Friendly** - Easy development workflow with Docker Compose profiles
- **⚡ Efficient Builds** - Docker Bake for optimized image building and caching
- **🎛️ Custom Node Management** - Integrated ComfyUI Manager for extension management
- **⚡ SageAttention 2++** - Optimized attention computation for 2-3x faster generation

### Key Features
- **Multi-profile architecture** - GPU and CPU profiles with extended SageAttention 2++ support
- **Persistent storage** - Your models, configs, and outputs survive container restarts
- **Virtual environment** - Isolated Python environment for ComfyUI extensions
- **Environment-based configuration** - All settings controlled via environment variables
- **Optimized CI/CD** - Docker Bake-based workflows with efficient caching
- **Performance optimization** - SageAttention 2++ for faster attention computation

## 🚀 Quick Start

```bash
# 1. Clone and setup
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

EOF

# 2. Start ComfyUI (choose one)
# Standard GPU mode (recommended for most users)
docker compose comfy-nvidia up -d

# Extended GPU mode with SageAttention 2++ (2-3x faster attention)
docker compose comfy-cuda-extended up -d

# CPU mode (universal)
docker compose comfy-cpu up -d

# 3. Open ComfyUI at http://localhost:8188 (or your configured port)
```

**That's it!** ComfyUI is now running. For model setup and advanced configuration, see the documentation below.

## 🚀 Performance Modes

### Standard GPU Mode (`comfy-nvidia`)
- **Best for**: Most users, general purpose
- **Performance**: Standard ComfyUI performance
- **Compatibility**: Works with all models and workflows

### Extended GPU Mode (`comfy-cuda-extended`) ⚡
- **Best for**: Power users, production workloads
- **Performance**: 2-3x faster attention computation with SageAttention 2++
- **Features**: 
  - Optimized attention mechanisms
  - Reduced VRAM usage
  - Better scaling with large models
  - Automatic fallback for incompatible operations
  - Library-only installation (no custom nodes required)
- **Requirements**: NVIDIA GPU with 8GB+ VRAM, CUDA 12.x

### CPU Mode (`comfy-cpu`)
- **Best for**: Systems without GPU, testing
- **Performance**: Slower but universal compatibility
- **Compatibility**: Works on any system

## 📁 Project Structure

```
ComfyUI-Docker/
├── 📚 docs/                          # Documentation
│   ├── index.md                      # Documentation overview
│   ├── user-guides/                  # User tutorials and guides
│   ├── development-guides/           # Development and CI/CD guides
│   └── project-management/           # Project planning and analysis
│
├── 🐳 services/                      # Docker service definitions
│   ├── runtime/                      # Runtime base images
│   │   ├── dockerfile.nvidia.runtime # NVIDIA GPU runtime
│   │   └── dockerfile.cpu.runtime    # CPU-only runtime
│   │
│   └── comfy/                        # Main ComfyUI service
│       ├── base/                     # Base ComfyUI image
│       │   ├── dockerfile.comfy.base # Base ComfyUI image
│       │   ├── startup.sh            # Container startup script
│       │   ├── entrypoint.sh         # Container entrypoint
│       │   ├── post_install.sh       # Post-installation setup
│       │   └── extra_model_paths.yaml # Model path configuration
│       │
│       └── extended/                 # Extended features
│           ├── dockerfile.comfy.cuda.extended # SageAttention 2++ image
│           ├── requirements.txt      # Extended dependencies
│           └── scripts/              # Performance optimization scripts
│
├── 📦 data/                          # Persistent data storage
├── 🖼️ output/                        # Generated image outputs

├── 🔧 .github/                       # GitHub Actions workflows
├── 📋 docker-compose.yml             # Main orchestration file
├── 🏗️ docker-bake.hcl                # Multi-stage build configuration
└── 📖 README.md                      # This file
```

### Key Directories Explained

- **`docs/`** - Complete documentation organized by audience (users, developers, project management)
- **`services/`** - Docker service definitions with multi-stage builds for different runtimes
- **`data/`** - Persistent storage for models, configs, and user data
- **`output/`** - Generated images and workflow outputs
- **`.github/`** - CI/CD workflows and GitHub configuration

## 📚 Documentation

- **[Documentation Index](docs/)** – Overview of all documentation

### For Users
- **[User Guides](docs/user-guides/)** – All user documentation
  - **[Quick Start](docs/user-guides/quick-start.md)** – Get running in 5 minutes
  - **[Usage Guide](docs/user-guides/usage.md)** – Daily operations and workflows
  - **[Configuration](docs/user-guides/configuration.md)** – Environment variables and performance tuning



### For Developers
- **[Development Guides](docs/development-guides/)** – All development documentation
  - **[Development](docs/development-guides/development.md)** – Building, contributing, and development workflow
  - **[CI/CD](docs/development-guides/ci-cd.md)** – Docker Bake workflows and local testing

### For Project Management
- **[Project Management](docs/project-management/)** – Project planning and analysis
  - **[Tasks & Roadmap](docs/project-management/tasks.md)** – Current issues, technical debt, and roadmap
  - **[Repository Analysis](docs/project-management/repository-analysis.md)** – Analysis of existing ComfyUI Docker repositories


## 🤝 Contributing

Contributions are welcome! Please see the [Development Guide](docs/development-guides/development.md) for development setup and contribution guidelines.

**Important**: Create a discussion first describing the problem and your proposed solution before implementing anything.

## ⚖️ License & Disclaimer

This project is provided under the terms specified in the [LICENSE](./LICENSE) file. Users are responsible for ensuring their use complies with all applicable laws and regulations.

The authors are not responsible for any content generated using this interface. Please use responsibly and ethically.

## 🙏 Acknowledgments

Special thanks to the amazing open source community behind these projects:

- **[ComfyUI](https://github.com/comfyanonymous/ComfyUI)** - The powerful node-based stable diffusion interface
- **[ComfyUI CLI](https://github.com/Comfy-Org/comfy-cli)** - Command-line interface for ComfyUI management
- **[AbdBarho/stable-diffusion-webui-docker](https://github.com/AbdBarho/stable-diffusion-webui-docker)** - Original Docker implementation inspiration
- **[CompVis/stable-diffusion](https://github.com/CompVis/stable-diffusion)** - The foundational stable diffusion research
- And the entire AI/ML open source community that makes this possible

---

**[⬆ Back to Top](#comfyui-docker)** | **[📚 Documentation](docs/)** | **[🐛 Issues](https://github.com/pixeloven/ComfyUI-Docker/issues)** | **[💬 Discussions](https://github.com/pixeloven/ComfyUI-Docker/discussions)**
