# App Structure Overhaul Project Plan

## Project Overview

**Goal**: Restructure the ComfyUI Docker deployment to use standard `/app` mounting practices, eliminating complex symlinking and simplifying configuration.

**Benefits**:
- ✅ Standard Docker app installation at `/app`
- ✅ Direct volume mounting (no symlinks)
- ✅ Simplified startup process
- ✅ Reduced environment variables
- ✅ Faster container initialization
- ✅ Better alignment with ComfyUI defaults

---

## Current vs Target Architecture

### Current Structure
```
/home/comfy/app/           ← ComfyUI installation (ephemeral)
/data/                     ← Volume mount point
/data/comfy/               ← COMFY_BASE_DIRECTORY
├── custom_nodes/          ← Symlinked to /home/comfy/app/custom_nodes
├── input/                 ← Symlinked to /home/comfy/app/input
├── models/                ← Symlinked to /home/comfy/app/models
├── output/                ← Symlinked to /home/comfy/app/output
├── temp/                  ← Symlinked to /home/comfy/app/temp
└── user/                  ← Symlinked to /home/comfy/app/user
```

### Target Structure
```
/app/                      ← ComfyUI installation (standard Docker practice)
├── custom_nodes/          ← Direct mount: ./data/custom_nodes
├── input/                 ← Direct mount: ./data/input
├── models/                ← Direct mount: ./data/models
├── output/                ← Direct mount: ./data/output
├── temp/                  ← Direct mount: ./data/temp
└── user/                  ← Direct mount: ./data/user
```

---

## Phase 1: Core Dockerfile Updates

### Phase 1.1: Runtime Base Images
- [ ] **Task 1.1.1**: Update `services/runtime/dockerfile.cuda.runtime`
  - Change WORKDIR to `/app`
  - Update any app-related paths
- [ ] **Task 1.1.2**: Update `services/runtime/dockerfile.cpu.runtime`
  - Change WORKDIR to `/app`
  - Update any app-related paths
- [ ] **Task 1.1.3**: Test runtime builds
  - `docker buildx bake runtime-cuda runtime-cpu`

### Phase 1.2: Core ComfyUI Image
- [ ] **Task 1.2.1**: Update `services/comfy/core/dockerfile.comfy.core`
  - Change WORKDIR from `/home/comfy` to `/app`
  - Update ComfyUI installation to use `/app` workspace
  - Remove `COMFY_DATA_DIRECTORY`, `COMFY_BASE_DIRECTORY`, `COMFY_APP_DIRECTORY`
  - Remove `COMFYUI_MODEL_PATH`, `COMFYUI_CUSTOM_NODES_PATH`
  - Update user setup for `/app` ownership
- [ ] **Task 1.2.2**: Test core builds
  - `docker buildx bake core-cuda core-cpu`

### Phase 1.3: Complete ComfyUI Image
- [ ] **Task 1.3.1**: Update `services/comfy/complete/dockerfile.comfy.cuda.complete`
  - Align with core image changes
  - Update any complete-specific paths
- [ ] **Task 1.3.2**: Test complete builds
  - `docker buildx bake complete-cuda`

---

## Phase 2: Startup Script Simplification

### Phase 2.1: Core Startup
- [ ] **Task 2.1.1**: Update `services/comfy/core/startup.sh`
  - Remove `--base-directory $COMFY_BASE_DIRECTORY`
  - Simplify to use ComfyUI defaults at `/app`
  - Remove environment variable dependencies
- [ ] **Task 2.1.2**: Update `services/comfy/core/entrypoint.sh`
  - Remove any symlink-related logic
  - Update paths to `/app`

### Phase 2.2: Complete Startup
- [ ] **Task 2.2.1**: Update `services/comfy/complete/startup.sh`
  - Remove `--base-directory $COMFY_BASE_DIRECTORY`
  - Update post-install script execution paths
- [ ] **Task 2.2.2**: Update `services/comfy/complete/entrypoint.sh`
  - Remove symlink-related logic
  - Update paths to `/app`

### Phase 2.3: Post-Install Scripts
- [ ] **Task 2.3.1**: Update `services/comfy/complete/scripts/00-setup-file-structure.sh`
  - Remove all symlink creation logic
  - Remove environment variable dependencies
  - Simplify to basic directory creation (if needed)
- [ ] **Task 2.3.2**: Update `services/comfy/complete/scripts/lib/custom-nodes.sh`
  - Update paths to use `/app/custom_nodes` directly
  - Remove `COMFY_BASE_DIRECTORY` dependencies

---

## Phase 3: Docker Compose Configuration

### Phase 3.1: Volume Mount Updates
- [ ] **Task 3.1.1**: Update `docker-compose.yml` for core-cuda service
  - Replace `/data` mount with direct mounts:
    - `${COMFY_DATA_PATH:-./data}/models:/app/models`
    - `${COMFY_DATA_PATH:-./data}/custom_nodes:/app/custom_nodes`
    - `${COMFY_DATA_PATH:-./data}/input:/app/input`
    - `${COMFY_DATA_PATH:-./data}/output:/app/output`
    - `${COMFY_DATA_PATH:-./data}/temp:/app/temp`
    - `${COMFY_DATA_PATH:-./data}/user:/app/user`
- [ ] **Task 3.1.2**: Update complete-cuda service volumes
- [ ] **Task 3.1.3**: Update core-cpu service volumes

### Phase 3.2: Environment Variable Cleanup
- [ ] **Task 3.2.1**: Remove environment variables from compose services
  - Remove `COMFY_DATA_DIRECTORY` references
  - Remove `COMFY_BASE_DIRECTORY` references
  - Keep `COMFY_PORT`, `CLI_ARGS`, `PUID`, `PGID`

### Phase 3.3: Scripts Mount Updates
- [ ] **Task 3.3.1**: Update scripts volume mount path
  - Change from `/home/comfy/app/scripts` to `/app/scripts`

---

## Phase 4: Build System Updates

### Phase 4.1: Docker Bake Configuration
- [ ] **Task 4.1.1**: Update `docker-bake.hcl`
  - Verify target configurations work with new structure
  - Update any hardcoded paths
- [ ] **Task 4.1.2**: Test all bake targets
  - `docker buildx bake all --print` (validate config)
  - `docker buildx bake runtime core complete`

### Phase 4.2: Multi-Instance Support
- [ ] **Task 4.2.1**: Update `MULTI_INSTANCE_PLAN.md`
  - Revise for new `/app` structure
  - Update environment variable references
- [ ] **Task 4.2.2**: Test multi-instance configurations

---

## Phase 5: Documentation Updates

### Phase 5.1: Core Documentation
- [ ] **Task 5.1.1**: Update `CLAUDE.md`
  - Revise architecture section
  - Update volume mounting examples
  - Remove obsolete environment variables
- [ ] **Task 5.1.2**: Update `README.md`
  - Update quick start examples
  - Revise volume mounting documentation

### Phase 5.2: User Guides
- [ ] **Task 5.2.1**: Update `docs/user-guides/configuration.md`
  - Remove `COMFY_BASE_DIRECTORY` references
  - Update volume examples
- [ ] **Task 5.2.2**: Update `docs/user-guides/scripts.md`
  - Update custom node installation paths
  - Revise examples for `/app` structure

### Phase 5.3: Examples and Scripts
- [ ] **Task 5.3.1**: Update any example docker-compose files
- [ ] **Task 5.3.2**: Update shell scripts in repository
- [ ] **Task 5.3.3**: Search and replace remaining references
  - `COMFY_BASE_DIRECTORY` → direct `/app` references
  - `/home/comfy/app` → `/app`

---

## Phase 6: Testing and Validation

### Phase 6.1: Build Testing
- [ ] **Task 6.1.1**: Full clean build test
  - `docker buildx bake all --no-cache`
- [ ] **Task 6.1.2**: Test all service profiles
  - `docker compose --profile core up -d`
  - `docker compose --profile complete up -d`
  - `docker compose --profile cpu up -d`

### Phase 6.2: Functionality Testing
- [ ] **Task 6.2.1**: Test model loading
  - Verify models mount correctly
  - Test checkpoint loading in ComfyUI
- [ ] **Task 6.2.2**: Test custom node installation
  - Verify custom nodes persist correctly
  - Test post-install script execution
- [ ] **Task 6.2.3**: Test input/output workflows
  - Verify file I/O works correctly
  - Test workflow persistence

### Phase 6.3: Migration Testing
- [ ] **Task 6.3.1**: Test data migration from old structure
  - Create migration guide if needed
  - Test with existing user data

---

## Phase 7: CI/CD and Release

### Phase 7.1: CI Pipeline Updates
- [ ] **Task 7.1.1**: Update `.github/workflows/ci.yml`
  - Update validation tests for new structure
  - Update environment variable references
- [ ] **Task 7.1.2**: Test CI pipeline
  - Verify all builds pass
  - Verify configuration validation

### Phase 7.2: Release Preparation
- [ ] **Task 7.2.1**: Create migration guide
  - Document breaking changes
  - Provide migration steps for existing users
- [ ] **Task 7.2.2**: Update version tags and changelogs
- [ ] **Task 7.2.3**: Create release notes

---

## Risk Assessment and Mitigation

### High Risk Items
1. **Data Loss Risk**: Direct volume mounting changes could affect existing user data
   - **Mitigation**: Create detailed migration guide, test with sample data
2. **Breaking Changes**: Users with custom configurations may be affected
   - **Mitigation**: Clear documentation of changes, provide migration examples
3. **Custom Node Compatibility**: Custom nodes expecting old paths
   - **Mitigation**: Test with popular custom nodes, document any issues

### Medium Risk Items
1. **CI/CD Pipeline**: Build system changes could break automation
   - **Mitigation**: Test in development branch, update CI incrementally
2. **Multi-Instance Support**: Complex configurations may need additional work
   - **Mitigation**: Phase 4.2 specifically addresses this

---

## Success Criteria

- [ ] All Docker builds complete successfully
- [ ] All compose profiles start and function correctly
- [ ] ComfyUI loads and can generate images
- [ ] Custom nodes install and work properly
- [ ] Data persists correctly across container restarts
- [ ] Performance is equal or better than current implementation
- [ ] Documentation is updated and accurate
- [ ] Migration path is clear for existing users

---

## Estimated Timeline

- **Phase 1**: 2-3 days (Core infrastructure changes)
- **Phase 2**: 1-2 days (Script simplification)
- **Phase 3**: 1 day (Compose configuration)
- **Phase 4**: 1 day (Build system)
- **Phase 5**: 1-2 days (Documentation)
- **Phase 6**: 2-3 days (Testing)
- **Phase 7**: 1 day (Release prep)

**Total Estimated Time**: 9-13 days

---

## Notes

- This plan assumes familiarity with the existing codebase
- Each phase should be completed and tested before proceeding
- Regular commits and testing after each major task
- Consider creating a development branch for this work
- Backup existing configurations before starting