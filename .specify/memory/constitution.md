<!--
Sync Impact Report
==================
Version change: N/A → 1.0.0 (Initial ratification)
Modified principles: N/A (Initial creation)
Added sections:
  - Core Principles (5 principles)
  - Container Standards
  - Development Workflow
  - Governance
Removed sections: N/A
Templates requiring updates:
  - .specify/templates/plan-template.md: ✅ No updates required (generic Constitution Check reference)
  - .specify/templates/spec-template.md: ✅ No updates required (no constitution references)
  - .specify/templates/tasks-template.md: ✅ No updates required (no constitution references)
Follow-up TODOs: None
-->

# ComfyUI-Docker Constitution

## Core Principles

### I. Container-First Architecture

All deployments MUST be containerized with Docker as the primary runtime target. Multi-stage builds are REQUIRED to optimize image size and build caching. Each deployment profile (core, complete, cpu) MUST maintain independent, functional containers.

**Rationale**: Containerization ensures reproducible deployments across development, staging, and production environments while enabling GPU acceleration and consistent dependency management.

### II. Profile Isolation

Each deployment profile MUST be independently functional and testable. Profiles MUST NOT share runtime state or dependencies that could cause cross-profile failures. Configuration differences between profiles MUST be explicit and documented.

**Rationale**: Users select profiles based on their hardware and use case. Profile isolation prevents "works on complete, fails on core" scenarios and simplifies debugging.

### III. GPU & Performance Transparency

GPU requirements and performance characteristics MUST be clearly documented for each profile. Performance optimizations (SageAttention, CUDA versions) MUST be optional or profile-specific, never breaking CPU fallback. Resource requirements (VRAM, disk space) MUST be stated upfront.

**Rationale**: Users need accurate information to select appropriate profiles and troubleshoot performance issues. Hidden GPU dependencies cause silent failures.

### IV. Data Persistence Boundaries

User data (models, outputs, custom nodes, configurations) MUST be volume-mounted and survive container rebuilds. Container images MUST NOT embed user-specific data or credentials. Default data paths MUST be overridable via environment variables.

**Rationale**: Separating ephemeral container state from persistent user data prevents data loss during updates and enables flexible storage configurations.

### V. CI/CD & Image Provenance

All published container images MUST be built through automated CI/CD pipelines. Images MUST be tagged with version, build date, and commit SHA for traceability. Breaking changes to image behavior MUST increment major version or use distinct tags.

**Rationale**: Automated builds ensure reproducibility and security. Clear versioning enables users to pin stable versions and rollback when needed.

## Container Standards

- Base images MUST use official NVIDIA CUDA images for GPU profiles and official Python images for CPU profiles
- Dockerfiles MUST use multi-stage builds to separate build-time and runtime dependencies
- Images MUST support arbitrary user IDs (PUID/PGID) for permission compatibility
- Health checks SHOULD be implemented for orchestration readiness
- Image layers MUST be ordered to maximize cache utilization (dependencies before application code)

## Development Workflow

- All Dockerfile changes MUST be tested against all three profiles (core-cuda, complete-cuda, core-cpu) before merge
- docker-compose.yml changes MUST maintain backward compatibility with existing volume mounts
- New custom nodes for complete profile MUST be added via the snapshot system, not inline Dockerfile modifications
- Environment variable additions MUST be documented in README.md and relevant user guides
- Pre-built GHCR images MUST be updated within 7 days of upstream ComfyUI releases

## Governance

This constitution supersedes all other practices for the ComfyUI-Docker project. Amendments require:

1. Documentation of the proposed change with rationale
2. Verification that all three deployment profiles remain functional
3. Update to this constitution with version increment

**Version Policy**:
- MAJOR: Breaking changes to deployment behavior, removed profiles, or incompatible volume mount changes
- MINOR: New features, new profiles, or expanded configuration options
- PATCH: Documentation updates, bug fixes, dependency updates without behavior changes

**Compliance Review**: All pull requests MUST verify adherence to these principles. Reviewers SHOULD check that container standards and development workflow requirements are met.

**Version**: 1.0.0 | **Ratified**: 2026-01-30 | **Last Amended**: 2026-01-30
