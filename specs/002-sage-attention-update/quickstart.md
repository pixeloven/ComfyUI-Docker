# Quickstart: SageAttention Update and SageAttention 3 Support

## Overview

This feature updates SageAttention 2 to v2.2.0-build.15 and adds SageAttention 3 (sageattn3) v1.0.0 support to the complete-cuda Docker image.

## Prerequisites

- Docker with buildx support
- NVIDIA GPU with CUDA 12.8+ support
- Access to the ComfyUI-Docker repository

## Implementation Steps

### Step 1: Update extra-requirements.txt

Edit `services/comfy/complete/extra-requirements.txt`:

```diff
- # SageAttention 2.2.0 (pre-built) - CUDA 12.9.1 + torch 2.8 (build.10)
+ # SageAttention 2.2.0 + SageAttn3 3.0.0 (pre-built) - CUDA 12.9.1 + Python 3.12 (build.15)
  https://github.com/pixeloven/SageAttention/releases/download/v2.2.0-build.15/sageattention-2.2.0-290.129-cp312-cp312-linux_x86_64.whl
+ https://github.com/pixeloven/SageAttention/releases/download/v2.2.0-build.15/sageattn3-1.0.0-290.129-cp312-cp312-linux_x86_64.whl
```

### Step 2: Rebuild Docker Image

```bash
cd /path/to/ComfyUI-Docker
docker buildx bake complete-cuda
```

### Step 3: Validate Installation

Start the container and verify both packages are installed:

```bash
# Start container
docker compose --profile complete up -d

# Verify SageAttention 2
docker compose exec complete-cuda python -c "import sageattention; print(f'SageAttention: {sageattention.__version__}')"

# Verify SageAttention 3
docker compose exec complete-cuda python -c "import sageattn3; print('SageAttn3: OK')"
```

## Expected Output

```
SageAttention: 2.2.0
SageAttn3: OK
```

## Troubleshooting

### Build Fails with Download Error
- Verify the wheel URLs are accessible
- Check network connectivity to GitHub

### Import Error for sageattn3
- Ensure the wheel URL was added correctly
- Verify the container was rebuilt after the change

### GPU Compatibility
- SageAttention 3 targets Blackwell GPU architecture
- On older GPUs, sageattn3 import should succeed but may not provide acceleration
