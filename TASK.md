# ComfyUI Docker Project - Issues & Ideas Consolidation

## 🚨 Current Issues & Technical Debt

### Critical Issues
- [ ] **Model Path Mapping Conflict**: Fix mappings between `/data/models` and `data/config/comfy/models` (the latter is created by ComfyManager)
- [ ] **ONNX Integration**: Make ONNX support configurable/optional rather than baked into the image
- [x] **Virtual Environment**: Ensure everything runs in a proper venv as some extensions expect it
- [ ] **Docker Compose Readability**: Update docker-compose.yml to be more readable and maintainable

### Configuration Issues
- [ ] **Port Hardcoding**: Port 8188 is hardcoded in Dockerfile (noted in docker-compose.yml line 27)
- [ ] **Volume Mapping**: Generally better workflow volume mappings needed
- [ ] **Persistent Extensions**: Need persistent volume for custom extensions
- [ ] **Cache Directory**: Unclear XDG_CACHE_HOME usage (commented out in entrypoint.sh)

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
- [ ] **Documentation**: Comprehensive docs structure and easy to use site

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
3. Improve Docker Compose readability
4. Resolve port hardcoding

### Phase 2: Platform Expansion (Short-term)
1. Add CPU/ROCM support
2. Implement manifest-based model management
3. Create workflow management system

### Phase 3: Advanced Features (Medium-term)
1. Easy setup for advanced ComfyUI workflows/extensions
2. Workflow versioning and private repo integration
3. Management application development

### Phase 4: Platform Evolution (Long-term)
1. Explore Trellis/OpenUI/Ollama integration
2. Make repository structure decision (harmony project)
3. Evaluate multi-modal AI workflow support

## 📝 Notes & Comments from Code

### From docker-compose.yml
- Model mapping issues between `/data/models` and `data/config/comfy/models`
- Need to fix volume mappings and move `/output` to `/data/output`
- Consider whether repo scope should expand beyond stable diffusion

### From Dockerfile
- ONNX should be optional and configurable at runtime
- Explore using ComfyUI CLI instead of direct Python execution
- Virtual environment setup needs improvement

### From entrypoint.sh
- XDG_CACHE_HOME usage unclear and commented out
- Base directory and output directory configuration working well

---

*Last Updated: 2025-06-27*
*This document consolidates all project issues, ideas, and roadmap items for easy reference and planning.*