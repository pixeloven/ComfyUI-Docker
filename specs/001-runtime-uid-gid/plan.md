# Implementation Plan: Runtime UID/GID Support

**Branch**: `001-runtime-uid-gid` | **Date**: 2026-01-30 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-runtime-uid-gid/spec.md`

## Summary

Enable arbitrary user/group ID support in ComfyUI Docker containers at runtime. Currently, the container builds with hardcoded UID/GID 1000:1000, causing `getpwuid` errors when run with different user IDs. The solution uses gosu for secure privilege dropping from a root entrypoint, dynamically creating users/groups as needed.

## Technical Context

**Language/Version**: Bash (entrypoint scripts), Dockerfile syntax
**Primary Dependencies**: gosu (privilege dropping), standard Linux utilities (groupadd, useradd, getent, chown)
**Storage**: N/A (filesystem permissions only)
**Testing**: Manual container testing with different PUID/PGID values across all profiles
**Target Platform**: Linux containers (CUDA 12.9, Ubuntu 24.04 base)
**Project Type**: Docker infrastructure
**Performance Goals**: Container startup within 30 seconds (per SC-001)
**Constraints**: Must maintain backward compatibility with existing deployments (no PUID/PGID = UID 1000:GID 1000)
**Scale/Scope**: 3 deployment profiles (core-cuda, complete-cuda, core-cpu)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Container-First Architecture | ✅ PASS | Changes are within Docker build/runtime scope |
| II. Profile Isolation | ✅ PASS | Same entrypoint.sh shared by all profiles; no cross-profile dependencies |
| III. GPU & Performance Transparency | ✅ PASS | No GPU impact; startup time constraint documented (30s) |
| IV. Data Persistence Boundaries | ✅ PASS | Feature specifically addresses volume permissions without embedding user data |
| V. CI/CD & Image Provenance | ✅ PASS | Changes go through existing CI/CD pipeline |

**Container Standards Compliance**:
- ✅ Multi-stage builds preserved
- ✅ Arbitrary user IDs supported (this is the feature being implemented)
- ✅ Image layer ordering maintained

**Development Workflow Compliance**:
- ✅ Must test all three profiles before merge
- ✅ Backward compatible with existing docker-compose configurations
- ✅ Environment variables documented in README

## Project Structure

### Documentation (this feature)

```text
specs/001-runtime-uid-gid/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output (N/A for this feature)
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (N/A - no API)
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
services/
├── comfy/
│   ├── core/
│   │   ├── dockerfile.comfy.core    # Modify: Remove hardcoded user, add gosu
│   │   ├── entrypoint.sh            # Replace: Dynamic user creation + privilege drop
│   │   └── startup.sh               # No changes needed
│   └── complete/
│       └── dockerfile.comfy.cuda.complete  # Minor: Inherit entrypoint changes
├── runtime/
│   ├── dockerfile.cpu.runtime       # Modify: Install gosu
│   └── dockerfile.cuda.runtime      # Modify: Install gosu

examples/
├── core-gpu/
│   └── docker-compose.yml           # Modify: Add PUID/PGID env vars
├── core-cpu/
│   └── docker-compose.yml           # Modify: Add PUID/PGID env vars
└── complete-gpu/
    └── docker-compose.yml           # Modify: Add PUID/PGID env vars

docs/
└── user-guides/
    └── running.md                   # Modify: Document PUID/PGID usage
```

**Structure Decision**: Docker infrastructure project - modifications to Dockerfiles, entrypoint scripts, and compose files. No application source code changes.

## Complexity Tracking

No constitution violations requiring justification.
