# Migration Plan: Runtime Scripts to Native ComfyUI Tooling

## Research Summary (January 2025)

### ComfyUI CLI Capabilities

**Verified Commands (comfy-cli):**
- `comfy node install <name|url>` - Install custom nodes from registry or git
- `comfy node update all` - Update all installed nodes
- `comfy node save-snapshot --output <file.json|.yaml>` - Save installation state
- `comfy node restore-snapshot <file.json|.yaml>` - Restore from snapshot
- `comfy node install-deps --deps <file.json>` - Install from dependency spec
- `comfy node install-deps --workflow <file.json|.png>` - Install workflow dependencies
- `comfy node deps-in-workflow --workflow <file> --output <deps.json>` - Extract deps

### Snapshot Format (ComfyUI-Manager)

**Structure (JSON/YAML):**
```json
{
  "comfyui": "d1533d9c0f1dde192f738ef1b745b15f49f41e02",  // Commit hash
  "custom_nodes": {
    "https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git": {
      "url": "https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git",
      "name": "ComfyUI-Custom-Scripts",
      "hash": "abc123...",  // Commit hash
      "pip": ["package1", "package2"],
      "disabled": false
    }
  },
  "file_custom_nodes": {
    "custom_script.py": {
      "disabled": false,
      "filename": "custom_script.py"
    }
  },
  "pips": {
    "package-name": "1.2.3"  // Version pinning for all custom node deps
  }
}
```

**Key Features:**
- ✅ Commit hash pinning for reproducibility
- ✅ Pip dependency tracking with versions
- ✅ Disabled state for each node
- ✅ Official ComfyUI-Manager format (stable, not beta)
- ✅ Human-readable and version-controllable

### Lock File Status (comfy-lock.yaml)

**Current State:**
- **Beta/WIP feature** as of January 2025
- **NOT recommended for production use**
- Minimal documentation and examples
- Format may change without notice
- **No evidence of `comfy node install-deps --deps=comfy-lock.yaml` working**

**Recommendation:** Use snapshots instead of comfy-lock.yaml

---

## Current State Analysis

### Complete Image Setup (Problems to Solve)

The **complete** image currently:
- ✅ Has pre-built wheels in [extra-requirements.txt](services/comfy/complete/extra-requirements.txt)
- ❌ Installs **13 custom nodes** via **runtime** bash scripts (02-08)
- ❌ Uses custom library functions (`install_custom_node_from_git`)
- ❌ Executes post-install scripts **on first container startup**
- ❌ Creates `.post_install_done` marker to prevent re-running
- ❌ Non-reproducible builds (always pulls latest `main` branch)

### Installed Custom Nodes Inventory (13 nodes)

**Platform Essentials** (1 node)
- ComfyUI-Custom-Scripts - https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git

**Workflow Enhancers** (4 nodes)
- rgthree-comfy - https://github.com/rgthree/rgthree-comfy.git
- ComfyUI-KJNodes - https://github.com/kijai/ComfyUI-KJNodes.git
- ComfyUI-TeaCache - https://github.com/TechCowboy/ComfyUI-TeaCache.git
- ComfyUI-Inspire-Pack - https://github.com/ltdrdata/ComfyUI-Inspire-Pack.git

**Detection/Segmentation** (2 nodes)
- ComfyUI-Impact-Pack - https://github.com/ltdrdata/ComfyUI-Impact-Pack.git
- ComfyUI-Impact-Subpack - https://github.com/ltdrdata/ComfyUI-Impact-Subpack.git

**Image Enhancers** (3 nodes)
- ComfyUI_UltimateSDUpscale - https://github.com/ssitu/ComfyUI_UltimateSDUpscale.git
- ComfyUI-RMBG - https://github.com/Jcd1230/rembg-comfyui-node.git
- ComfyUI-IC-Light - https://github.com/kijai/ComfyUI-IC-Light.git

**Control Systems** (2 nodes)
- ComfyUI_IPAdapter_plus - https://github.com/cubiq/ComfyUI_IPAdapter_plus.git
- comfyui_controlnet_aux - https://github.com/Fannovel16/comfyui_controlnet_aux.git

**Distribution Systems** (1 node)
- ComfyUI_NetDist - https://github.com/city96/ComfyUI_NetDist.git

---

## Migration Options

### Option A: Runtime Snapshot Restoration (Minimal Changes)

**Use native snapshot restoration at container startup.**

**Pros:**
- Uses official, stable tooling (not beta)
- Minimal changes to existing architecture
- Easy to update (just regenerate snapshot)
- Commit hash pinning for reproducibility
- Pip dependency version locking built-in

**Cons:**
- Still requires runtime installation (slower startup)
- Keeps `.post_install_done` marker pattern
- Larger attack surface (git operations at runtime)

**Implementation:**

Create `services/comfy/complete/production-snapshot.json`:
```json
{
  "comfyui": "main",
  "custom_nodes": {
    "https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git": {
      "url": "https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git",
      "hash": "main",
      "disabled": false
    }
    // ... all 13 nodes
  }
}
```

Update [startup.sh](services/comfy/complete/startup.sh):
```bash
#!/bin/bash
set -e

if [ ! -f .post_install_done ]; then
    log_info "Restoring custom nodes from snapshot..."
    comfy node restore-snapshot /app/production-snapshot.json
    touch .post_install_done
    log_success "Custom nodes restored successfully"
fi

comfy env
comfy tracking disable
comfy launch -- --listen --port $COMFY_PORT $CLI_ARGS
```

Update [dockerfile.comfy.cuda.complete](services/comfy/complete/dockerfile.comfy.cuda.complete):
```dockerfile
COPY --chown=comfy:comfy ./production-snapshot.json /app/production-snapshot.json
```

---

### Option B: Build-Time Snapshot Restoration (Recommended) ⭐

**Install custom nodes during Docker build using snapshot.**

**Pros:**
- ✅ Zero runtime installation delay
- ✅ Immutable node versions baked into image
- ✅ Better for production (no git operations at runtime)
- ✅ No `.post_install_done` marker needed
- ✅ Uses official, stable tooling
- ✅ Reproducible builds with commit hash pinning

**Cons:**
- Larger image size (includes all nodes in layers)
- Requires image rebuild to update nodes
- Longer build times

**Implementation:**

Create `services/comfy/complete/production-snapshot.json`:
```json
{
  "comfyui": "main",
  "custom_nodes": {
    "https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git": {
      "url": "https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git",
      "hash": "main",
      "disabled": false
    }
    // ... all 13 nodes
  },
  "pips": {
    "package-name": "1.2.3"  // Auto-populated by save-snapshot
  }
}
```

Update [dockerfile.comfy.cuda.complete](services/comfy/complete/dockerfile.comfy.cuda.complete):
```dockerfile
FROM core-cuda as complete-cuda

# Copy snapshot file
COPY --chown=comfy:comfy ./production-snapshot.json /app/production-snapshot.json

# Install custom nodes at BUILD TIME
RUN --mount=type=cache,mode=0755,uid=1000,gid=1000,target=/home/comfy/.cache/pip \
    source $VENV_PATH/bin/activate && \
    cd /app && \
    comfy node restore-snapshot /app/production-snapshot.json

# Install pre-built wheels and common dependencies
COPY --chown=comfy:comfy ./extra-requirements.txt /tmp/extra-requirements.txt
RUN --mount=type=cache,mode=0755,uid=1000,gid=1000,target=/home/comfy/.cache/pip \
    source $VENV_PATH/bin/activate && \
    pip install --no-cache-dir -r /tmp/extra-requirements.txt && \
    rm /tmp/extra-requirements.txt

# Simple startup (no post-install needed)
COPY --chown=comfy:comfy ./startup.sh /app/startup.sh
RUN chmod +x /app/startup.sh

CMD ["/app/startup.sh"]
```

Simplified [startup.sh](services/comfy/complete/startup.sh):
```bash
#!/bin/bash
set -e

# No post-install needed, nodes are already installed at build time
comfy env
comfy tracking disable
comfy launch -- --listen --port $COMFY_PORT $CLI_ARGS
```

**Files to Delete:**
- `services/comfy/complete/scripts/00-setup-file-structure.sh`
- `services/comfy/complete/scripts/01-setup-example-workflows.sh`
- `services/comfy/complete/scripts/02-install-platform-essentials.sh`
- `services/comfy/complete/scripts/03-install-workflow-enhancers.sh`
- `services/comfy/complete/scripts/04-install-detection-segmentation.sh`
- `services/comfy/complete/scripts/05-install-image-enhancers.sh`
- `services/comfy/complete/scripts/06-install-control-systems.sh`
- `services/comfy/complete/scripts/07-install-video-animation.sh`
- `services/comfy/complete/scripts/08-install-distribution-systems.sh`
- `services/comfy/complete/scripts/lib/custom-nodes.sh`
- `services/comfy/complete/scripts/lib/logging.sh` (optional, keep if used elsewhere)

---

### Option C: User-Provided Snapshots (Advanced Flexibility)

**Allow users to provide their own snapshot via environment variable.**

**Pros:**
- Maximum user flexibility
- Teams can share custom snapshots
- Easy to swap between configurations
- Still uses official tooling

**Cons:**
- More complex setup for beginners
- Requires documentation
- Validation needed for user-provided files

**Implementation:**

Update [docker-compose.yml](docker-compose.yml):
```yaml
services:
  complete-cuda:
    environment:
      - COMFY_SNAPSHOT_FILE=${COMFY_SNAPSHOT_FILE:-/app/production-snapshot.json}
    volumes:
      # Optional: mount custom snapshot
      - ${COMFY_SNAPSHOT_FILE_PATH:-./services/comfy/complete/production-snapshot.json}:/app/custom-snapshot.json:ro
```

Update [.env.example](.env.example):
```bash
# Snapshot configuration
COMFY_SNAPSHOT_FILE=/app/custom-snapshot.json  # Default: /app/production-snapshot.json
COMFY_SNAPSHOT_FILE_PATH=./my-team-snapshot.json  # Optional: custom snapshot path
```

Update [startup.sh](services/comfy/complete/startup.sh):
```bash
#!/bin/bash
set -e

SNAPSHOT_FILE=${COMFY_SNAPSHOT_FILE:-/app/production-snapshot.json}

if [ ! -f .post_install_done ]; then
    if [ -f "$SNAPSHOT_FILE" ]; then
        log_info "Restoring from snapshot: $SNAPSHOT_FILE"
        comfy node restore-snapshot "$SNAPSHOT_FILE"
        touch .post_install_done
    else
        log_warning "No snapshot file found at $SNAPSHOT_FILE, skipping node installation"
    fi
fi

comfy env
comfy tracking disable
comfy launch -- --listen --port $COMFY_PORT $CLI_ARGS
```

---

## Recommended Approach: Option B (Build-Time Installation) ⭐

### Why Option B?

1. **Production-ready:** Eliminates runtime overhead and git operations
2. **Official tooling:** Uses stable snapshot format (not beta lock files)
3. **Reproducible:** Commit hashes ensure exact versions
4. **Simpler:** No runtime scripts to maintain
5. **Aligned with goals:** Pre-built optimizations, zero custom solutions

### Migration Phases

#### Phase 1: Generate Production Snapshot

**Goal:** Create initial `production-snapshot.json` from current installation

**Steps:**
1. Run complete image with current runtime scripts
2. Let scripts install all 13 nodes
3. Execute: `comfy node save-snapshot --output production-snapshot.json`
4. Commit snapshot file to repository
5. Optionally: Pin commit hashes for reproducibility

**Testing:**
```bash
docker compose --profile complete up -d
docker compose exec complete-cuda bash
comfy node save-snapshot --output /app/production-snapshot.json
docker cp $(docker compose ps -q complete-cuda):/app/production-snapshot.json ./services/comfy/complete/
```

#### Phase 2: Update Dockerfile for Build-Time Installation

**Goal:** Install nodes during build instead of runtime

**Changes:**
1. Update [dockerfile.comfy.cuda.complete](services/comfy/complete/dockerfile.comfy.cuda.complete) with snapshot restoration
2. Simplify [startup.sh](services/comfy/complete/startup.sh) (remove post-install logic)
3. Test build locally: `docker buildx bake complete-cuda --load`
4. Verify nodes exist: `docker run --rm complete-cuda ls /app/custom_nodes`

#### Phase 3: Remove Runtime Scripts

**Goal:** Clean up obsolete installation scripts

**Files to delete:**
- All numbered scripts (00-08.sh)
- `lib/custom-nodes.sh`
- Optionally keep `lib/logging.sh` if useful elsewhere

**Update:**
- [CLAUDE.md](CLAUDE.md) - Remove script documentation
- README.md - Update deployment instructions

#### Phase 4: CI/CD Integration

**Goal:** Automate snapshot generation and validation

**Changes:**
1. Add weekly job to generate fresh snapshot with latest commits
2. Create PR with updated snapshot for review
3. Validate build succeeds with new snapshot
4. Document snapshot update workflow

---

## Snapshot Maintenance Workflow

### Updating Custom Nodes

**Option 1: Automated (Recommended)**
```bash
# GitHub Action runs weekly
- Install current snapshot
- Run: comfy node update all
- Run: comfy node save-snapshot --output new-snapshot.json
- Create PR with updated snapshot
```

**Option 2: Manual**
```bash
# Local development
docker compose --profile complete up -d
docker compose exec complete-cuda bash
comfy node update all
comfy node save-snapshot --output /app/updated-snapshot.json
# Copy snapshot out and commit
```

### Adding New Nodes

```bash
# Install new node
comfy node install https://github.com/author/new-node.git

# Update snapshot
comfy node save-snapshot --output /app/production-snapshot.json

# Rebuild image
docker buildx bake complete-cuda --load
```

### Pinning Specific Commits

Edit `production-snapshot.json` manually:
```json
{
  "custom_nodes": {
    "https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git": {
      "hash": "abc123def456..."  // Change from "main" to specific commit
    }
  }
}
```

---

## Testing Plan

### Test 1: Generate Initial Snapshot
```bash
docker compose --profile complete up -d
docker compose exec complete-cuda comfy node save-snapshot --output /app/test-snapshot.json
docker compose cp complete-cuda:/app/test-snapshot.json ./
cat test-snapshot.json  # Verify structure
```

### Test 2: Build-Time Installation
```bash
# Build with snapshot
docker buildx bake complete-cuda --load

# Verify nodes installed
docker run --rm --entrypoint bash ghcr.io/pixeloven/comfyui-docker/complete:cuda-latest -c "ls /app/custom_nodes"

# Verify startup time (should be fast)
time docker compose --profile complete up -d
```

### Test 3: Snapshot Restoration
```bash
# Delete custom nodes
docker compose exec complete-cuda rm -rf /app/custom_nodes/*

# Restore from snapshot
docker compose exec complete-cuda comfy node restore-snapshot /app/production-snapshot.json

# Verify nodes restored
docker compose exec complete-cuda ls /app/custom_nodes
```

### Test 4: User-Provided Snapshot (Option C)
```bash
# Create custom snapshot
echo '{"comfyui": "main", "custom_nodes": {}}' > custom-snapshot.json

# Test with custom snapshot
COMFY_SNAPSHOT_FILE_PATH=./custom-snapshot.json docker compose --profile complete up -d
```

---

## Success Criteria

- [x] Uses official ComfyUI tooling exclusively (no custom bash functions)
- [x] Reproducible builds via snapshot commit hashes
- [ ] Zero runtime installation overhead (build-time only)
- [ ] Version-controllable snapshot in git
- [ ] Clear upgrade path for custom nodes
- [ ] Minimal breaking changes to existing deployments
- [ ] Documentation updated for snapshot workflow
- [ ] CI/CD automation for snapshot updates

---

## Open Questions

### 1. Should we pin commit hashes immediately?
**Options:**
- Start with `"hash": "main"` for easier updates
- Pin specific commits for stability
- Hybrid: pin stable nodes, use `main` for active development

**Recommendation:** Start with `main`, pin after initial validation

### 2. How to handle custom node dependencies?
**Current:** Snapshot format includes `"pips"` field for version pinning

**Action:** Verify `comfy node restore-snapshot` installs pip dependencies automatically

### 3. What about example workflows (script 01)?
**Options:**
- Keep `01-setup-example-workflows.sh` as optional runtime script
- Bake example workflows into image at build time
- Remove entirely (users can add their own)

**Recommendation:** Bake into image or provide separate download script

### 4. Weekly rebuild strategy?
**Current:** Weekly no-cache builds pull latest dependencies

**With snapshots:**
- Weekly job generates new snapshot with latest commits
- Creates PR for review before merging
- Allows validation before production deployment

---

## Next Steps

**Decision Required:**
1. ✅ Confirmed: Use snapshots (stable) instead of lock files (beta)
2. Choose deployment mode: Runtime (Option A) or Build-Time (Option B)?
3. Do we want user flexibility (Option C)?

**Action Items:**
- [ ] Generate initial production-snapshot.json from current installation
- [ ] Test snapshot restoration in core image
- [ ] Update Dockerfile for build-time installation (Option B)
- [ ] Simplify startup.sh
- [ ] Remove runtime scripts (02-08)
- [ ] Update documentation (CLAUDE.md, README.md)
- [ ] Test builds and deployments
- [ ] Create CI workflow for snapshot updates
