# Implementation Plan: SageAttention Update and SageAttention 3 Support

**Branch**: `002-sage-attention-update` | **Date**: 2026-01-31 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-sage-attention-update/spec.md`

## Summary

Update SageAttention 2 to v2.2.0-build.15 and add SageAttention 3 (sageattn3) v3.0.0 support to the complete-cuda Docker image. The implementation involves updating `extra-requirements.txt` with the new wheel URLs, rebuilding the Docker images, and validating that both packages import successfully.

## Technical Context

**Language/Version**: Python 3.12, Dockerfile syntax, Bash scripts
**Primary Dependencies**: PyTorch 2.8+, CUDA 12.9.1, sageattention 2.2.0, sageattn3 3.0.0
**Storage**: N/A (package installation only)
**Testing**: Manual import verification via `python -c "import ..."`, Docker build validation
**Target Platform**: Linux x86_64 (Docker containers with NVIDIA GPU support)
**Project Type**: Container-based multi-stage build (services structure)
**Performance Goals**: N/A (performance optimization library - users self-select based on GPU)
**Constraints**: Must match container Python/PyTorch/CUDA versions; complete-cuda profile only
**Scale/Scope**: Single file change (`extra-requirements.txt`), rebuild complete-cuda image

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Container-First Architecture | ✅ PASS | Changes only affect Docker build via requirements file |
| II. Profile Isolation | ✅ PASS | SageAttention only in complete-cuda profile; core/cpu unaffected |
| III. GPU & Performance Transparency | ✅ PASS | SageAttention is optional, GPU-only, documented in performance.md |
| IV. Data Persistence Boundaries | ✅ PASS | No user data affected; package installed in container layer |
| V. CI/CD & Image Provenance | ✅ PASS | Standard image rebuild via existing docker-bake.hcl |

**Container Standards Check**:
- ✅ Uses official NVIDIA CUDA base image (12.9.1-base-ubuntu24.04)
- ✅ Multi-stage build maintained (runtime → core → complete)
- ✅ PUID/PGID support unchanged
- ✅ Cache-friendly layer ordering preserved (deps before app)

**Development Workflow Check**:
- ✅ Change isolated to complete profile only
- ✅ docker-compose.yml unchanged
- ✅ Extra dependencies added via requirements file (not inline Dockerfile)
- ⚠️ Documentation update may be needed if sageattn3 requires user action

## Project Structure

### Documentation (this feature)

```text
specs/002-sage-attention-update/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── spec.md              # Feature specification
└── checklists/
    └── requirements.md  # Specification quality checklist
```

### Source Code (repository root)

```text
services/
├── runtime/
│   └── dockerfile.cuda.runtime    # CUDA 12.9.1 base (unchanged)
└── comfy/
    ├── core/
    │   └── dockerfile.comfy.core  # Core image (unchanged)
    └── complete/
        ├── dockerfile.comfy.cuda.complete  # Complete image (unchanged)
        └── extra-requirements.txt          # ← UPDATE: Add sageattn3 wheel

docs/
└── user-guides/
    └── performance.md             # ← May need update for sageattn3 docs
```

**Structure Decision**: Minimal change - single file modification to add wheel URL. No new directories, no structural changes.

## Complexity Tracking

No constitution violations requiring justification. This is a straightforward dependency update.

## Implementation Approach

### Phase 0: Research (Complete)

Research confirmed via GitHub API:
- SageAttention 2 wheel already current: `sageattention-2.2.0-290.129-cp312-cp312-linux_x86_64.whl`
- SageAttention 3 available: `sageattn3-3.0.0-cp312-cp312-linux_x86_64.whl`
- Both from same release: v2.2.0-build.15

### Phase 1: Implementation Tasks

1. **Update extra-requirements.txt**
   - Add sageattn3 wheel URL
   - Update comment to reflect both packages

2. **Rebuild Docker Images**
   - Run `docker buildx bake complete-cuda`
   - Verify build completes successfully

3. **Validate Installation**
   - Test SageAttention 2: `python -c "import sageattention; print(sageattention.__version__)"`
   - Test SageAttention 3: `python -c "import sageattn3; print('sageattn3 OK')"`

4. **Documentation Review** (if needed)
   - Check if performance.md needs sageattn3 usage notes
