# Research: Runtime UID/GID Support

**Feature**: 001-runtime-uid-gid
**Date**: 2026-01-30

## Research Topics

### 1. gosu vs su-exec for Privilege Dropping

**Decision**: Use gosu

**Rationale**:
- gosu is the industry standard for Docker privilege dropping (used by official PostgreSQL, MySQL, Redis images)
- Properly handles signal forwarding via exec (no intermediate shell process)
- Well-maintained with regular security updates
- Clarification session confirmed gosu-only requirement (no su-exec fallback)

**Alternatives Considered**:
- `su-exec`: Smaller binary, Alpine-friendly, but less common in Ubuntu-based images
- `su`: Leaves parent process running as root, poor signal handling
- `sudo`: Overkill for single privilege drop, has security configuration overhead

**Implementation Notes**:
```dockerfile
# Install gosu in runtime Dockerfiles
RUN apt-get update && \
    apt-get install -y --no-install-recommends gosu && \
    rm -rf /var/lib/apt/lists/* && \
    gosu nobody true  # Verify installation
```

### 2. Dynamic User/Group Creation Pattern

**Decision**: Create user/group at container startup in entrypoint, not at build time

**Rationale**:
- Build-time user creation cannot accommodate runtime-specified UIDs
- linuxserver.io base images use this pattern successfully at scale
- Allows single image to work with any UID/GID combination

**Implementation Pattern**:
```bash
# Create group if GID doesn't exist
if ! getent group "$PGID" > /dev/null 2>&1; then
    groupadd -g "$PGID" "$USERNAME"
fi

# Create user if UID doesn't exist
if ! getent passwd "$PUID" > /dev/null 2>&1; then
    useradd -u "$PUID" -g "$PGID" -d /app -s /bin/bash -M "$USERNAME"
fi
```

**Edge Cases Handled**:
- UID/GID already exists: Reuse existing user/group
- UID=0 (root): Log warning but allow
- Invalid values: Fail fast with clear error message

### 3. Directory Ownership Strategy

**Decision**: Minimal chown of critical directories only

**Rationale**:
- Recursive chown on large directories (models, outputs) is slow and unnecessary
- Application directories (/app, /app/ComfyUI) need write access
- Mounted volumes retain host ownership, which is the desired behavior

**Critical Directories**:
- `/app` - Application root
- `/app/ComfyUI` - ComfyUI installation directory

**Excluded from chown**:
- `/app/models` - Large, read-mostly, mounted volume
- `/app/output` - Mounted volume, inherits host permissions
- `/app/custom_nodes` - Mounted volume
- Other mounted data directories

### 4. Entrypoint Architecture

**Decision**: Root entrypoint with exec gosu for privilege drop

**Rationale**:
- Container must start as root to create users/groups
- exec gosu ensures clean process tree (no lingering root process)
- Matches Docker best practices for privilege dropping

**Process Flow**:
```
Container Start (root)
    ↓
entrypoint.sh (root)
    ├── Validate PUID/PGID
    ├── Create group if needed
    ├── Create user if needed
    ├── chown critical directories
    └── exec gosu $PUID:$PGID ...
            ↓
        startup.sh (non-root)
            ↓
        python main.py (non-root)
```

### 5. Backward Compatibility Strategy

**Decision**: Default PUID=1000, PGID=1000 when not specified

**Rationale**:
- Matches current hardcoded behavior
- Existing docker-compose files work unchanged
- Most Linux desktop users have UID 1000

**Implementation**:
```bash
PUID=${PUID:-1000}
PGID=${PGID:-1000}
```

### 6. Input Validation Requirements

**Decision**: Fail fast on invalid PUID/PGID with clear error message

**Rationale**:
- Silent fallback could mask configuration errors
- Early failure is easier to debug than runtime permission issues
- Clarification session confirmed this approach

**Validation Rules**:
- Must be numeric
- Must be positive (≥1) or zero (with warning)
- Must be within valid range (typically ≤65534 for compatibility)

**Error Format**:
```
ERROR: Invalid PUID value 'abc'. Must be a positive integer.
```

### 7. Logging Strategy

**Decision**: Single minimal log line for startup confirmation

**Rationale**:
- Clarification session specified minimal logging
- Reduces log noise in production
- Still provides debugging information

**Log Output**:
```
Starting with UID:GID = 3000:3000
```

**Additional Logging**:
- Warning if PUID=0 (root)
- Error messages for validation failures

## Research Summary

| Topic | Decision | Confidence |
|-------|----------|------------|
| Privilege dropping tool | gosu only | High |
| User creation timing | Runtime (entrypoint) | High |
| Directory ownership | Minimal (/app, /app/ComfyUI only) | High |
| Process architecture | Root entrypoint → exec gosu | High |
| Default values | PUID=1000, PGID=1000 | High |
| Validation behavior | Fail fast with error message | High |
| Logging verbosity | Minimal (single line) | High |

All research topics resolved. No NEEDS CLARIFICATION items remain.
