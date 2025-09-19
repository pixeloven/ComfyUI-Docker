# Multi-Instance ComfyUI Docker Project Plan

## Problem Statement
Enable multiple ComfyUI Docker installations to share a single data directory while avoiding conflicts in custom nodes, user configurations, and temporary files. Models should remain safely shareable while instance-specific data needs proper isolation.

## Key Findings

**Current Structure Analysis:**
- Current setup uses flat `/data/comfy/` structure with symlinks
- All instance-specific data (custom_nodes, user configs, temp files) would conflict
- Models directory is safely shareable
- comfy-cli provides workspace management capabilities that can inform our approach

**Identified Conflicts:**
1. **High-Risk**: `custom_nodes/` - Different versions, dependencies, incompatible nodes
2. **High-Risk**: `user/` - User-specific configs, themes, settings
3. **Medium-Risk**: `temp/` - Temporary processing files
4. **Medium-Risk**: `output/` - Generated images (could be organized by instance)
5. **Low-Risk**: `input/` - Input images (generally shareable)
6. **Safe**: `models/` - Model files can be safely shared

## Recommended Data Directory Structure

```
data/
├── shared/                          # Safely shareable resources
│   ├── models/                      # All model types
│   │   ├── checkpoints/
│   │   ├── vae/
│   │   ├── loras/
│   │   ├── embeddings/
│   │   ├── controlnet/
│   │   └── ...
│   └── input/                       # Shared input images
├── instances/                       # Instance-specific data
│   ├── instance-core/               # Core GPU instance
│   │   ├── custom_nodes/
│   │   ├── user/
│   │   ├── temp/
│   │   └── output/
│   ├── instance-complete/           # Complete GPU instance
│   │   ├── custom_nodes/
│   │   ├── user/
│   │   ├── temp/
│   │   └── output/
│   └── instance-cpu/                # CPU-only instance
│       ├── custom_nodes/
│       ├── user/
│       ├── temp/
│       └── output/
└── meta/                           # Multi-instance management
    ├── instance-registry.json      # Track active instances
    ├── shared-configs/             # Shareable configurations
    └── backup-snapshots/           # Instance backups
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

### Phase 4: Advanced Features
**Goal**: Enhance multi-instance capabilities with advanced features

**Tasks**:
- Implement shared configuration templates
- Add cross-instance model sharing verification
- Create instance isolation monitoring and health checks
- Develop workflow sharing system between instances

**Deliverables**:
- Enhanced instance management features
- Monitoring and health check system
- Inter-instance workflow sharing capabilities

## Implementation Recommendations

1. **Environment Variables**: Use `COMFY_INSTANCE_ID` to distinguish instances
2. **Service Profiles**: Extend existing Docker Compose profiles for multi-instance
3. **Gradual Rollout**: Implement with backward compatibility, allowing single-instance operation
4. **Safety First**: Include extensive validation and conflict detection
5. **Documentation**: Comprehensive migration guides and troubleshooting docs

## Technical Implementation Details

### Environment Variables for Multi-Instance Support

```bash
# Instance identification
COMFY_INSTANCE_ID=core               # Unique identifier for instance
COMFY_MULTI_INSTANCE=true           # Enable multi-instance mode

# Updated directory paths
COMFY_DATA_DIRECTORY=/data           # Root data directory
COMFY_SHARED_DIRECTORY=/data/shared  # Shared resources
COMFY_INSTANCE_DIRECTORY=/data/instances/${COMFY_INSTANCE_ID}  # Instance-specific data
COMFY_BASE_DIRECTORY=${COMFY_INSTANCE_DIRECTORY}  # Instance base (for compatibility)
```

### Docker Compose Service Examples

```yaml
services:
  core-cuda-instance1:
    image: ${COMFY_IMAGE:-ghcr.io/pixeloven/comfyui-docker/core:cuda-latest}
    environment:
      - COMFY_INSTANCE_ID=core-1
      - COMFY_MULTI_INSTANCE=true
      - COMFY_PORT=8188
    ports:
      - "8188:8188"
    volumes:
      - ${COMFY_DATA_PATH:-./data}:/data
    profiles: [multi-core]

  complete-cuda-instance1:
    image: ${COMFY_IMAGE:-ghcr.io/pixeloven/comfyui-docker/complete:cuda-latest}
    environment:
      - COMFY_INSTANCE_ID=complete-1
      - COMFY_MULTI_INSTANCE=true
      - COMFY_PORT=8189
    ports:
      - "8189:8189"
    volumes:
      - ${COMFY_DATA_PATH:-./data}:/data
    profiles: [multi-complete]
```

### Migration Strategy

1. **Detection**: Check for existing single-instance data structure
2. **Backup**: Create backup of current data before migration
3. **Transform**: Move instance-specific data to new structure
4. **Symlink**: Create compatibility symlinks for seamless transition
5. **Validate**: Verify migration success and data integrity

This approach leverages your existing Docker architecture while providing safe, manageable multi-instance operation with shared model resources and isolated instance-specific data.