# Tasks & Roadmap

Current issues, technical debt, and roadmap items for the ComfyUI Docker project.

## 🚨 Current Issues & Technical Debt

### Critical Issues
- [ ] **Model Path Mapping Conflict**: Fix mappings between `/data/models` and `data/config/comfy/models` (the latter is created by ComfyManager)
- [ ] **ONNX Integration**: Make ONNX support configurable/optional rather than baked into the image
- [x] **Virtual Environment**: Ensure everything runs in a proper venv as some extensions expect it
- [x] **Docker Compose Readability**: Refactored to per-example docker-compose.yml files in `examples/`
- [x] **ComfyUI Manager Integration**: Automatically installs ComfyUI Manager v3.33.8
- [x] **Post-Install Script**: Automated setup of directories and environment

### Configuration Issues
- [x] **Port Hardcoding**: Port 8188 is now configurable via COMFY_PORT environment variable
- [x] **Environment Variables**: All configuration is now properly externalized via environment variables
- [ ] **Volume Mapping**: Generally better workflow volume mappings needed
- [ ] **Persistent Extensions**: Need persistent volume for custom extensions
- [x] **Cache Directory**: XDG_CACHE_HOME is properly configured in dockerfile.comfy.core

### Multi-Instance & Workspace Support
- [ ] **Multiple Workspaces**: Support running multiple ComfyUI instances with different configurations
- [ ] **Instance Isolation**: Separate data directories, ports, and configurations per workspace
- [ ] **Workspace Management**: Tools/scripts for creating, managing, and switching between workspaces
- [ ] **Resource Allocation**: GPU allocation and resource management for multiple instances

### Build & Deployment
- [ ] **Version Pinning**: Pin/configurable versions for dependencies
- [ ] **Multi-Architecture**: Add ROCM/ZLUDA support for AMD GPUs
- [ ] **Docker Swarm**: Add support for Docker Swarm deployment

## 🔧 Infrastructure & Tooling

### CI/CD Pipeline
- [x] **Basic CI/CD**: Implemented with GitHub Actions
- [x] **Local Testing**: Act integration for local CI testing
- [x] **Docker Caching**: Build caching implemented in CI/CD
- [ ] **Security Scanning**: Trivy vulnerability scanning implemented

### Development Workflow
- [x] **Containerized Testing**: Test suite runs in containers
- [x] **Documentation**: Comprehensive docs structure and easy to use site

## 💡 Future Enhancements

### Model & Workflow Management
- [ ] **Manifest System**: Update setup to use a manifest/mapping system or some other form of management tooling for user data (plugins, models, workflows, etc.)
- [ ] **Management App**: Create an app for managing manifests, outputs, etc.
- [ ] **Private Workflow Repo**: Create private GitHub repo for workflow data
- [ ] **Workflow Versioning**: Implement versioning system for workflows
- [ ] **Model Documentation**: Add descriptions and readmes for models (similar to Stability Matrix)

### Platform Evolution
- [x] **Drop A111 Support**: Remove Automatic1111 Docker support, focus on ComfyUI with preset workflows
- [ ] **Project Restructure**: Move under PixelOven and either merge into harmony project or keep separate as comfy-docker
- [ ] **Multi-Modal Support**: Consider expanding beyond image generation (audio, text, etc.)

### Alternative Platforms
- [ ] **Forge Integration**: Consider Stable Diffusion WebUI Forge support
- [ ] **InvokeAI Integration**: Evaluate InvokeAI integration
- [ ] **Scope Decision**: Decide if repo is for image generation only or general AI workflows

## 📋 Roadmap Priority

### Phase 1: Fix Current Issues (Immediate)
1. Fix ComfyUI container model path mappings
2. Make ONNX support configurable
3. Implement multi-workspace support
4. Improve volume mappings for better workflow management
5. ✅ Create comprehensive configuration documentation
6. ✅ Update all documentation to reflect current application state (refactored to examples/ directories)

### Phase 2: Platform Expansion (Short-term)
1. Add CPU/ROCM support
2. Implement manifest-based model management
3. Create workflow management system
4. Versioned builds and multi [architecture](https://medium.com/womenintechnology/multi-architecture-builds-are-possible-with-docker-compose-kind-of-2a4e8d166c56)

### Phase 3: Advanced Features (Medium-term)
1. Easy setup for advanced ComfyUI workflows/extensions
2. Workflow versioning and private repo integration
3. Management application development
4. Advanced multi-instance orchestration

### Phase 4: Platform Evolution (Long-term)
1. Explore Trellis/OpenUI/Ollama integration
2. Make repository structure decision (harmony project)
3. Evaluate multi-modal AI workflow support

## 🆕 New Priorities Based on Comparative Analysis

### Multi-Architecture Support (High Priority)
- [ ] **AMD ROCm Support**: Add AMD GPU compatibility (from YanWenKun, ai-dock)
- [ ] **ARM64 Support**: Apple Silicon and ARM server support
- [ ] **Multiple CUDA Versions**: Support for different CUDA releases
- [ ] **Cross-Platform Testing**: Ensure compatibility across architectures

### Cloud Deployment Features (High Priority)
- [ ] **Vast.ai Templates**: Pre-configured templates for Vast.ai deployment
- [ ] **RunPod Templates**: Pre-configured templates for RunPod deployment
- [ ] **Cloud Documentation**: Dedicated cloud deployment guides
- [ ] **Optimized Images**: Smaller, cloud-ready variants
- [ ] **Auto-scaling Support**: Cloud-native scaling capabilities

### Security & Configuration (Medium Priority)
- [ ] **Optional Password Protection**: Default security with authentication options
- [ ] **Token Support**: CivitAI, HuggingFace integration for model downloads
- [ ] **Auto-update Features**: Configurable ComfyUI updates
- [ ] **Enhanced Environment Variables**: More comprehensive configuration options

### Service Orchestration (Medium Priority)
- [ ] **Supervisor Integration**: Multi-service orchestration (from ai-dock)
- [ ] **API Wrapper Service**: ComfyUI API service management
- [ ] **Service Health Monitoring**: Health checks and monitoring
- [ ] **Memory Management**: Built-in VRAM clearing and optimization

### Enhanced User Experience (Medium Priority)
- [ ] **Runtime Permission Flexibility**: Enhanced UID/GID configuration (from mmartial)
- [ ] **WSL2 Optimization**: Better Windows Subsystem for Linux support
- [ ] **Extension Automation**: Automated custom node installation
- [ ] **Extension Marketplace**: Integrated extension discovery and management

## 📝 Notes & Comments from Code

### From example docker-compose.yml files
- Deployment configs moved to `examples/` directories (`core-gpu`, `complete-gpu`, `core-cpu`)
- Each example has its own `docker-compose.yml` and `.env.example`
- Service name is `comfyui` in all examples; container names: `comfyui-core-gpu`, `comfyui-complete-gpu`, `comfyui-core-cpu`
- Model mapping issues between `/data/models` and `data/config/comfy/models`
- Port configuration is now properly handled via environment variables

### From Dockerfile
- ONNX should be optional and configurable at runtime
- Explore using ComfyUI CLI instead of direct Python execution
- Virtual environment setup is working well

### From entrypoint.sh
- XDG_CACHE_HOME is properly configured in dockerfile.comfy.core
- Base directory and output directory configuration working well

### Multi-Workspace Requirements
- Need separate docker-compose files or profiles for different workspaces
- Each workspace should have isolated data directories
- Port allocation strategy for multiple instances
- GPU resource allocation and management
- Workspace-specific configuration management

### References
- [radiatingreverberations/comfyui-docker](https://github.com/radiatingreverberations/comfyui-docker)
- [mmartial/ComfyUI-Nvidia-Docker](https://github.com/mmartial/ComfyUI-Nvidia-Docker)
- [YanWenKun/ComfyUI-Docker](https://github.com/YanWenKun/ComfyUI-Docker)
- [ai-dock/comfyui](https://github.com/ai-dock/comfyui)
---

**[⬆ Back to Project Management](index.md)** | **[⬆ Back to Documentation Index](../index.md)** | **[🐛 Report Issues](https://github.com/pixeloven/ComfyUI-Docker/issues)**

*Last Updated: 2025-01-27 - Documentation updated to match current application state and include comparative analysis with ai-dock/comfyui*