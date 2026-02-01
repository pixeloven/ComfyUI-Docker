# Research: SageAttention Update and SageAttention 3 Support

**Date**: 2026-01-31
**Feature**: 002-sage-attention-update

## Summary

Research to determine the correct wheel files for updating SageAttention 2 and adding SageAttention 3 support to the complete-cuda Docker image.

## Findings

### 1. Current State

**File**: `services/comfy/complete/extra-requirements.txt`

Current SageAttention installation:
```
# SageAttention 2.2.0 (pre-built) - CUDA 12.9.1 + torch 2.8 (build.10)
https://github.com/pixeloven/SageAttention/releases/download/v2.2.0-build.13/sageattention-2.2.0-290.129-cp312-cp312-linux_x86_64.whl
```

**Note**: The comment says "build.10" but the URL already points to build.13. The wheel is current.

### 2. Available Wheels in v2.2.0-build.13

Source: GitHub API query of release assets

| Package | Version | Wheel Filename | Platform |
|---------|---------|----------------|----------|
| sageattention | 2.2.0 | sageattention-2.2.0-290.128-cp312-cp312-linux_x86_64.whl | CUDA 12.8 |
| sageattention | 2.2.0 | sageattention-2.2.0-290.129-cp312-cp312-linux_x86_64.whl | CUDA 12.9 |
| sageattn3 | 3.0.0 | sageattn3-3.0.0-cp312-cp312-linux_x86_64.whl | Linux x86_64 |

### 3. Container Environment

**File**: `services/runtime/dockerfile.cuda.runtime`

- Base image: `nvidia/cuda:12.9.1-base-ubuntu24.04`
- Python version: 3.12 (cp312)
- CUDA version: 12.9.1

### 4. Wheel Selection

**Decision**: Use CUDA 12.9 wheel (290.129) for SageAttention 2, add sageattn3 3.0.0

**Rationale**:
- Container uses CUDA 12.9.1, so 290.129 wheel is the correct match
- The current sageattention wheel is already correct (290.129 for CUDA 12.9)
- sageattn3 wheel appears platform-generic (no CUDA version suffix)

**Alternatives Considered**:
- CUDA 12.8 wheel (290.128): Rejected - would be suboptimal for 12.9.1 runtime

### 5. SageAttention 3 Package Structure

**Finding**: sageattn3 is a separate package, NOT a submodule of sageattention

**Evidence**:
- Separate wheel file in release
- Different version number (3.0.0 vs 2.2.0)
- Different package name (sageattn3 vs sageattention)

**Import Pattern**:
```python
# SageAttention 2
import sageattention

# SageAttention 3
import sageattn3
```

## Download URLs

**SageAttention 2** (already in place):
```
https://github.com/pixeloven/SageAttention/releases/download/v2.2.0-build.13/sageattention-2.2.0-290.129-cp312-cp312-linux_x86_64.whl
```

**SageAttention 3** (to be added):
```
https://github.com/pixeloven/SageAttention/releases/download/v2.2.0-build.13/sageattn3-3.0.0-cp312-cp312-linux_x86_64.whl
```

## Conclusions

1. SageAttention 2 wheel is already current (v2.2.0-build.13, 290.129)
2. Only need to add sageattn3 wheel URL to extra-requirements.txt
3. Update comment to reflect accurate build version and include sageattn3
