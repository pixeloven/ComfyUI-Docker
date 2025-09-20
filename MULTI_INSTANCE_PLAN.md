# Multi-Instance ComfyUI Docker Project Plan

## Problem Statement
Enable multiple ComfyUI Docker instances to safely share resources while avoiding conflicts. Some resources (like models) can be shared between instances, while others (like custom nodes and user configs) must be isolated per instance.

## Key Findings

**Current Structure Analysis:**
- Current setup uses flat `/data/comfy/` structure with symlinks
- All instance-specific data (custom_nodes, user configs, temp files) would conflict
- Models directory is safely shareable
- comfy-cli provides workspace management capabilities that can inform our approach

**Distribution Systems Available:**
- **ComfyUI_NetDist** (enabled): Network-based model distribution and caching across infrastructure
- **ComfyUI-Distributed** (available): Multi-node distributed computing for workflow execution
- **ComfyUI-MultiGPU** (available): Single-node multi-GPU optimization with Virtual VRAM management

**Identified Conflicts:**
1. **High-Risk**: `custom_nodes/` - Different versions, dependencies, incompatible nodes
2. **High-Risk**: `user/` - User-specific configs, themes, settings
3. **Medium-Risk**: `temp/` - Temporary processing files
4. **Medium-Risk**: `output/` - Generated images (could be organized by instance)
5. **Low-Risk**: `input/` - Input images (generally shareable)
6. **Safe**: `models/` - Model files can be safely shared

## Required Directory Structure

```
storage/
├── shared/                          # Shareable resources
│   ├── models/                      # All model types (safe to share)
│   │   ├── checkpoints/
│   │   ├── vae/
│   │   ├── loras/
│   │   ├── embeddings/
│   │   └── ...
│   └── input/                       # Common input images (safe to share)
└── instances/                       # Instance-specific data
    └── {instance-id}/               # Per-instance isolation
        ├── custom_nodes/            # Instance-specific nodes
        ├── user/                    # Instance-specific configs
        ├── temp/                    # Instance-specific temp files
        └── output/                  # Instance-specific outputs
```

**Container View:**
```
/shared/                            # Read-only shared resources
├── models/                         # Mounted from shared storage
└── input/                          # Mounted from shared storage
/instance/                          # Read-write instance data
├── custom_nodes/                   # Mounted from instance storage
├── user/                           # Mounted from instance storage
├── temp/                           # Mounted from instance storage
└── output/                         # Mounted from instance storage
```

## Project Phases

### Phase 1: Foundation & Design
**Goal**: Establish multi-instance data structure and update Docker configuration

**Tasks**:
- Create new data directory structure with shared/instances/meta organization
- Update Docker Compose to support instance-specific environment variables
- Modify startup scripts to handle instance-aware symlink creation
- Create instance identification system (via environment variables)

**Deliverables**:
- Updated docker-compose.yml with multi-instance service definitions
- Modified startup scripts for instance-aware directory setup
- Documentation for new data structure

### Phase 2: Instance Management System
**Goal**: Implement tooling for managing multiple instances

**Tasks**:
- Create instance registry system to track active/configured instances
- Develop CLI utilities for instance creation, deletion, and management
- Implement safety checks to prevent instance naming conflicts
- Create backup/snapshot system for instance configurations

**Deliverables**:
- Instance management CLI script
- Instance registry and metadata system
- Backup/restore functionality

### Phase 3: Migration & Compatibility
**Goal**: Provide migration path from single-instance to multi-instance setup

**Tasks**:
- Create migration script for existing single-instance data
- Implement backward compatibility mode for existing setups
- Add validation system to detect and resolve data conflicts
- Create automated testing for migration scenarios

**Deliverables**:
- Migration tooling and documentation
- Compatibility layer for existing installations
- Comprehensive testing suite

### Phase 4: Distribution & Advanced Features
**Goal**: Enhance multi-instance capabilities with distribution systems and advanced features

**Tasks**:
- Enable ComfyUI-Distributed for multi-node workflow execution
- Configure ComfyUI_NetDist for intelligent model caching
- Implement shared configuration templates
- Add cross-instance model sharing verification
- Create instance isolation monitoring and health checks
- Develop workflow sharing system between instances

**Deliverables**:
- Distribution system integration
- Enhanced instance management features
- Intelligent model caching and distribution
- Monitoring and health check system
- Inter-instance workflow sharing capabilities

## Implementation Summary

### Completed Changes

**1. Simplified Startup Script** (`services/comfy/complete/scripts/00-setup-file-structure.sh`)
- ✅ **Default Instance ID**: `COMFY_INSTANCE_ID` defaults to `"comfy"` for all users
- ✅ **Unified Logic**: Removed all conditionals - everyone uses the same pattern
- ✅ **Consistent Mounts**: All instances use `/shared/` and `/instance/` mount points
- ✅ **No Backward Compatibility Needed**: New unified approach for all users

**2. Environment Variables**
- ✅ `COMFY_INSTANCE_ID` - Defaults to `"comfy"`, can be overridden for multi-instance
- ✅ `COMFY_SHARED_PATH` - Host path for shared resources (default: `./storage/shared`)
- ✅ `COMFY_INSTANCES_PATH` - Host path for instance data (default: `./storage/instances`)

**3. Docker Compose Organization**
- ✅ **Split Configuration**: `docker-compose.yml` (single-instance) + `docker-compose.multi.yml` (multi-instance)
- ✅ **Unified Mounts**: All services use same storage pattern
- ✅ **Simple Usage**: No profiles needed - separate files for different use cases

### Implementation Approach
1. **Unified Pattern**: All users get the same `/shared/` + `/instance/` structure
2. **Default Instance**: Single-instance users automatically use `comfy` instance ID
3. **Storage Agnostic**: Host manages storage type (local, NFS, cloud storage, etc.)
4. **Simpler Code**: No conditionals or backward compatibility complexity

## Technical Implementation Details

### Current Environment Variables

```bash
# Instance identification (defaults to "comfy" for single-instance)
COMFY_INSTANCE_ID=comfy              # Unique identifier for instance

# Storage paths (used by Docker Compose)
COMFY_SHARED_PATH=./storage/shared        # Host path for shared resources
COMFY_INSTANCES_PATH=./storage/instances  # Host path for instance data

# Container mount points (set by startup script)
COMFY_SHARED_DIRECTORY=/shared            # Shared resources in container
COMFY_BASE_DIRECTORY=/instance            # Instance data in container
```

### Current Usage Examples

**Single-Instance (docker-compose.yml):**
```bash
# Uses default "comfy" instance automatically
docker compose up -d                      # Core
docker compose --profile complete up -d   # Complete
docker compose --profile cpu up -d        # CPU

# Results in: storage/instances/comfy/ for this instance
```

**Multi-Instance (docker-compose.multi.yml):**
```bash
# Runs two separate instances
docker compose -f docker-compose.multi.yml up -d

# Instance 01: localhost:8188 -> storage/instances/instance-01/
# Instance 02: localhost:8189 -> storage/instances/instance-02/
```

**Environment Configuration (.env):**
```bash
# Customize storage paths
COMFY_SHARED_PATH=./storage/shared        # Can be local, NFS mount, etc.
COMFY_INSTANCES_PATH=./storage/instances  # Can be local, NFS mount, etc.
PUID=1000
PGID=1000
```

### Example Storage Configurations

**Local Storage:**
```bash
COMFY_SHARED_PATH=./storage/shared
COMFY_INSTANCES_PATH=./storage/instances
```

**NFS Storage:**
```bash
COMFY_SHARED_PATH=/mnt/nfs/comfy/shared
COMFY_INSTANCES_PATH=/mnt/nfs/comfy/instances
```

**Cloud Storage:**
```bash
COMFY_SHARED_PATH=/mnt/s3fs/comfy/shared
COMFY_INSTANCES_PATH=/mnt/s3fs/comfy/instances
```

### Migration Strategy

**From Legacy Setup:**
1. **Move Data**: Copy existing data from `./data/` to `./storage/instances/comfy/`
2. **Update Environment**: Set `COMFY_SHARED_PATH` and `COMFY_INSTANCES_PATH` if using custom paths
3. **Test**: Verify new structure works with `docker compose up -d`

**No Migration Needed for New Installations** - The new structure is the default.

## Summary

✅ **Completed Implementation** - Multi-instance support with unified storage pattern

**Key Benefits:**
- **Simplified**: All users use the same storage structure
- **Flexible**: Works with any storage backend (local, NFS, cloud)
- **Clean**: No complex conditionals or legacy compatibility code
- **Scalable**: Easy to add more instances by adjusting Docker Compose files

**Usage:**
- **Single-instance**: `docker compose up -d` (automatic `comfy` instance)
- **Multi-instance**: `docker compose -f docker-compose.multi.yml up -d`
- **Custom storage**: Set environment variables in `.env` file