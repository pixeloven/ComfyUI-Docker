# Migration Plan: Custom Scripts to ComfyUI CLI

## Current State Analysis

### Complete Image Setup
The **complete** image currently:
- Installs **13 custom nodes** via runtime bash scripts (02-08)
- Uses custom library functions (`install_custom_node_from_git`)
- Executes post-install scripts on first container startup
- Creates `.post_install_done` marker to prevent re-running

### Installed Custom Nodes Inventory

**02-install-platform-essentials.sh** (1 node)
- ComfyUI-Custom-Scripts - https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git

**03-install-workflow-enhancers.sh** (4 nodes)
- rgthree-comfy - https://github.com/rgthree/rgthree-comfy.git
- ComfyUI-KJNodes - https://github.com/kijai/ComfyUI-KJNodes.git
- ComfyUI-TeaCache - https://github.com/TechCowboy/ComfyUI-TeaCache.git
- ComfyUI-Inspire-Pack - https://github.com/ltdrdata/ComfyUI-Inspire-Pack.git

**04-install-detection-segmentation.sh** (2 nodes)
- ComfyUI-Impact-Pack - https://github.com/ltdrdata/ComfyUI-Impact-Pack.git
- ComfyUI-Impact-Subpack - https://github.com/ltdrdata/ComfyUI-Impact-Subpack.git

**05-install-image-enhancers.sh** (3 nodes)
- ComfyUI_UltimateSDUpscale - https://github.com/ssitu/ComfyUI_UltimateSDUpscale.git
- ComfyUI-RMBG - https://github.com/Jcd1230/rembg-comfyui-node.git
- ComfyUI-IC-Light - https://github.com/kijai/ComfyUI-IC-Light.git

**06-install-control-systems.sh** (2 nodes)
- ComfyUI_IPAdapter_plus - https://github.com/cubiq/ComfyUI_IPAdapter_plus.git
- comfyui_controlnet_aux - https://github.com/Fannovel16/comfyui_controlnet_aux.git

**07-install-video-animation.sh** (0 active nodes)
- ComfyUI-AdvancedLivePortrait - Commented out

**08-install-distribution-systems.sh** (1 active node)
- ComfyUI_NetDist - https://github.com/city96/ComfyUI_NetDist.git
- ComfyUI-MultiGPU - Commented out
- ComfyUI-Distributed - Commented out

**Total: 13 actively installed custom nodes**

---

## ComfyUI CLI Capabilities

The `comfy-cli` provides three approaches for reproducible environments:

### 1. Snapshots
- **Commands:** `comfy node save-snapshot` / `comfy node restore-snapshot <name>`
- **List snapshots:** `comfy node show snapshot-list`
- **Format:** Compatible with ComfyUI-Manager snapshot format
- **Status:** Documented but minimal examples available

### 2. comfy-lock.yaml (Beta)
- **Format:** Declarative lock file for models + custom nodes
- **Features:**
  - Git URLs with commit hashes
  - Disabled/enabled state per node
  - Model URLs, paths, and hashes
- **Status:** Beta feature, still evolving
- **Compatibility:** Works with ComfyUI-Manager .yaml snapshots

### 3. Workflow-based Dependencies
- **Command:** `comfy node install-deps --workflow=<file.json>`
- **Use case:** Install nodes required by specific workflows
- **Limitation:** Less useful for base image setup

---

## Migration Options

### Option A: Snapshot-Based (Simplest)

Build a snapshot during image build time using the CLI itself.

**Pros:**
- Minimal changes to existing structure
- Uses official ComfyUI tooling
- Easy to update (just regenerate snapshot)

**Cons:**
- Requires builder machine to have nodes installed first
- Snapshot format is somewhat opaque
- Less version-controllable

**Implementation:**

```dockerfile
# In services/comfy/complete/dockerfile.comfy.cuda.complete
RUN comfy --workspace /app node install \
    https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git \
    https://github.com/rgthree/rgthree-comfy.git \
    # ... all 13 nodes
    && comfy node save-snapshot production-base
```

```bash
# In startup.sh
if [ ! -f .post_install_done ]; then
    comfy node restore-snapshot production-base
    touch .post_install_done
fi
```

---

### Option B: comfy-lock.yaml (Most Aligned with Standards) **[RECOMMENDED]**

Create a declarative lock file that comfy-cli can consume.

**Pros:**
- Version-controllable, human-readable
- Aligns with evolving ComfyUI standards
- Pin-able commit hashes for reproducibility
- Compatible with future ComfyUI ecosystem tools
- Easy to review in pull requests

**Cons:**
- Beta feature (may have breaking changes)
- Requires manual maintenance of YAML file
- Documentation is still sparse

**Implementation:**

Create `services/comfy/complete/comfy-lock.yaml`:
```yaml
custom_nodes:
  comfyui: main  # or specific commit hash
  git_custom_nodes:
    https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git:
      disabled: false
      hash: main  # or specific commit hash
    https://github.com/rgthree/rgthree-comfy.git:
      disabled: false
      hash: main
    https://github.com/kijai/ComfyUI-KJNodes.git:
      disabled: false
      hash: main
    https://github.com/TechCowboy/ComfyUI-TeaCache.git:
      disabled: false
      hash: main
    https://github.com/ltdrdata/ComfyUI-Inspire-Pack.git:
      disabled: false
      hash: main
    https://github.com/ltdrdata/ComfyUI-Impact-Pack.git:
      disabled: false
      hash: main
    https://github.com/ltdrdata/ComfyUI-Impact-Subpack.git:
      disabled: false
      hash: main
    https://github.com/ssitu/ComfyUI_UltimateSDUpscale.git:
      disabled: false
      hash: main
    https://github.com/Jcd1230/rembg-comfyui-node.git:
      disabled: false
      hash: main
    https://github.com/kijai/ComfyUI-IC-Light.git:
      disabled: false
      hash: main
    https://github.com/cubiq/ComfyUI_IPAdapter_plus.git:
      disabled: false
      hash: main
    https://github.com/Fannovel16/comfyui_controlnet_aux.git:
      disabled: false
      hash: main
    https://github.com/city96/ComfyUI_NetDist.git:
      disabled: false
      hash: main
```

Update Dockerfile:
```dockerfile
COPY --chown=comfy:comfy ./comfy-lock.yaml /app/comfy-lock.yaml
```

Update startup.sh:
```bash
if [ ! -f .post_install_done ]; then
    log_info "Installing custom nodes from comfy-lock.yaml..."
    comfy node install-deps --deps=/app/comfy-lock.yaml
    touch .post_install_done
    log_success "Custom nodes installed successfully"
fi
```

---

### Option C: Hybrid Build-Time + Lock File (Fastest Runtime)

Install nodes during **Docker build** instead of runtime, reducing startup time to zero.

**Pros:**
- Zero runtime installation delay
- Immutable node versions baked into image
- Better for production deployments
- No `.post_install_done` marker needed

**Cons:**
- Larger image size (includes all nodes in layers)
- Requires image rebuild to update nodes
- Longer build times

**Implementation:**

```dockerfile
# In services/comfy/complete/dockerfile.comfy.cuda.complete
COPY --chown=comfy:comfy ./comfy-lock.yaml /app/comfy-lock.yaml

RUN --mount=type=cache,mode=0755,uid=1000,gid=1000,target=/home/comfy/.cache/pip \
    source $VENV_PATH/bin/activate && \
    cd /app && \
    comfy node install-deps --deps=/app/comfy-lock.yaml && \
    pip install -r extra-requirements.txt
```

Simplified startup.sh:
```bash
# No post-install needed, just launch
comfy env
comfy tracking disable
comfy launch -- --listen --port $COMFY_PORT $CLI_ARGS
```

---

## Recommended Approach: **Option B with Phased Migration**

### Phase 1: Create comfy-lock.yaml alongside existing scripts
- Create the lock file from your current 13 nodes
- Keep existing bash scripts as fallback
- Test that comfy-cli can parse and use the lock file
- Validate in development environment

**Outcome:** Dual system running in parallel

### Phase 2: Migrate startup.sh to use lock file
- Update startup.sh to use `comfy node install-deps`
- Keep `.post_install_done` marker system
- Remove numbered scripts (02-08)
- Maintain backward compatibility with existing data volumes

**Outcome:** Single CLI-based installation system

### Phase 3: Cleanup and Documentation
- Remove bash script directory structure
- Remove `lib/custom-nodes.sh` (no longer needed)
- Keep `lib/logging.sh` if still useful
- Update CLAUDE.md with new approach
- Document lock file maintenance workflow

**Outcome:** Clean, maintainable system

### Phase 4 (Future): Move to build-time installation
- Once lock file is proven stable in production
- Implement Option C for faster container startups
- Update CI/CD weekly builds to detect upstream changes
- Consider image size optimizations

**Outcome:** Production-optimized zero-downtime deployments

---

## Open Questions & Research Needed

1. **Does `comfy node install-deps --deps=<file>` actually support comfy-lock.yaml?**
   - Documentation mentions the format but not the exact command syntax
   - May need to verify with testing or check CLI source code

2. **Can comfy-cli install from git URLs directly without lock file?**
   - Syntax: `comfy node install <git-url>` ?
   - Would simplify Option A

3. **How does comfy-cli handle node dependencies?**
   - Some nodes require other nodes (e.g., Impact-Subpack needs Impact-Pack)
   - Does CLI handle dependency resolution?

4. **Commit hash pinning workflow**
   - Should we pin to specific commits or use `main`?
   - How to update/refresh pinned versions?

5. **What happens on `restore-snapshot` with existing nodes?**
   - Does it skip already-installed nodes?
   - Does it update existing nodes?

---

## Testing Plan

### Test 1: Verify comfy-lock.yaml format
```bash
# Create minimal lock file with 1-2 nodes
# Run: comfy node install-deps --deps=test-lock.yaml
# Verify nodes are installed
```

### Test 2: Snapshot workflow
```bash
# Install nodes manually
# Run: comfy node save-snapshot test-snapshot
# Run: comfy node show snapshot-list
# Delete nodes
# Run: comfy node restore-snapshot test-snapshot
# Verify nodes are restored
```

### Test 3: Build-time installation
```bash
# Add comfy node install to Dockerfile
# Build image
# Verify nodes exist in /app/custom_nodes
# Test container startup time
```

---

## Success Criteria

- [ ] Reduced maintenance burden (no custom bash scripts to maintain)
- [ ] Uses official ComfyUI tooling exclusively
- [ ] Version-controllable node definitions
- [ ] Reproducible builds across environments
- [ ] Clear upgrade path for custom nodes
- [ ] Minimal breaking changes to existing deployments
- [ ] Documentation updated for new workflow

---

## Next Steps

**Decision Required:**
1. Which option (A, B, or C) aligns best with project goals?
2. Should we prioritize runtime flexibility or build-time optimization?
3. Do we need to test comfy-cli capabilities first?

**Action Items:**
- [ ] Create test environment to validate comfy-cli commands
- [ ] Generate initial comfy-lock.yaml
- [ ] Update documentation
- [ ] Implement phased migration
- [ ] Test with existing data volumes
