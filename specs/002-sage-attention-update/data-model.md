# Data Model: SageAttention Update and SageAttention 3 Support

**Feature**: 002-sage-attention-update
**Date**: 2026-01-31

## Overview

This feature involves package installation only. No persistent data model or state management is required.

## Configuration Entities

### Wheel Package References

| Entity | Location | Value |
|--------|----------|-------|
| SageAttention 2 Wheel | extra-requirements.txt | `sageattention-2.2.0-290.129-cp312-cp312-linux_x86_64.whl` |
| SageAttention 3 Wheel | extra-requirements.txt | `sageattn3-1.0.0-290.129-cp312-cp312-linux_x86_64.whl` |

### Package Metadata

| Package | Version | Python | CUDA Target |
|---------|---------|--------|-------------|
| sageattention | 2.2.0 | 3.12 | 12.9 |
| sageattn3 | 1.0.0 | 3.12 | 12.9 |

## Relationships

```
runtime-cuda (CUDA 12.9.1)
    └── core-cuda (PyTorch, Python 3.12)
        └── complete-cuda
            ├── sageattention 2.2.0
            └── sageattn3 1.0.0
```

## State

No state transitions. Packages are installed at image build time and available at container runtime.
