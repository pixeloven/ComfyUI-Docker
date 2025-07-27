# CrossOS Acceleritor Integration

This project now integrates [CrossOS Acceleritor](https://github.com/loscrossos/crossOS_acceleritor) to provide pre-built acceleration libraries for improved performance and faster builds.

## What is CrossOS Acceleritor?

CrossOS Acceleritor is a collection of pre-built, optimized acceleration libraries for AI workloads. It provides the "k-lite codec pack" equivalent for AI acceleration - a one-stop solution for acceleration libraries that are typically difficult to install.

## Benefits

- **Faster Build Times**: No source compilation required for supported libraries
- **Better Compatibility**: Pre-built wheels tested across different CUDA versions and GPU architectures
- **Additional Accelerators**: Access to acceleration libraries beyond what was previously available:
  - xFormers (memory efficient attention)
  - Triton (GPU programming framework)
- **Cross-Platform**: Works on Windows, Linux, and macOS
- **Optimized**: Libraries are compiled with the latest optimizations for modern RTX cards (30xx, 40xx, 50xx series)

## Supported Hardware

- **GPU**: NVIDIA RTX 30xx (Ampere), 40xx (Lovelace), 50xx (Blackwell) series
- **CUDA**: Compatible with CUDA 12.x (backwards compatible)
- **Python**: Python 3.12
- **PyTorch**: 2.7.1

## What Changed

### Before (Source Compilation)
- SageAttention was compiled from source during Docker build
- Required a separate builder stage with CUDA development tools
- Longer build times and potential compilation issues
- Limited to SageAttention only

### After (Pre-built Libraries)
- xFormers and Triton installed from pre-built wheels
- No source compilation required for supported libraries
- Faster, more reliable builds
- Access to multiple acceleration libraries
- **Note**: SageAttention is not included in this implementation due to compilation requirements

## Files Modified

- `services/comfy/extended/requirements-acceleritor.txt` - New requirements file with CrossOS Acceleritor libraries
- `services/comfy/extended/dockerfile.comfy.cuda.extended` - Updated to use pre-built libraries
- `services/comfy/extended/requirements.txt` - Simplified to remove build dependencies
- `docker-bake.hcl` - Removed SageAttention builder stage
- `services/comfy/extended/dockerfile.sage.builder` - Deleted (no longer needed)

## Current Implementation

The current implementation focuses on libraries that have reliable pre-built wheels available:

### Included Libraries
- **xFormers** (>=0.0.31) - Memory efficient attention mechanisms
- **Triton** (>=3.3.0) - GPU programming framework

### Additional Dependencies
- **onnxruntime-gpu** (>=1.22.0) - For IpAdapter support
- **insightface** (>=0.7.3) - For face recognition features
- **hidiffusion** (>=0.1.10) - For HiDiffusion support

## Usage

The extended CUDA image now automatically includes CrossOS Acceleritor libraries. No additional configuration is required - just build and run the extended image:

```bash
# Build the extended image with acceleration libraries
docker buildx bake comfy-cuda-extended

# Run with the extended image
docker run --gpus all -p 8188:8188 ghcr.io/pixeloven/comfyui-docker/comfy-cuda-extended:latest
```

## Future Enhancements

The CrossOS Acceleritor project provides additional libraries that could be integrated in the future:

- Flash Attention 2 - Fast attention implementation
- Sage Attention 2++ - Advanced attention mechanism (requires compilation)
- CausalConv1d - Causal convolution operations
- MambaSSM - State space model implementation

These libraries may be added as pre-built wheels become more widely available or if compilation requirements can be met.

## Troubleshooting

### Windows xFormers Issue
If you encounter issues with xFormers on Windows, you may need to rename some files as mentioned in the CrossOS Acceleritor documentation:

```bash
ren ".env_win\Lib\site-packages\xformers\pyd" "_C.pyd"
ren ".env_win\Lib\site-packages\xformers\flash_attn_3\pyd" "_C.pyd"
```

### Missing Python Headers
If you get errors about missing Python headers during installation, ensure you have Python 3.12 installed on your system (not from conda).

## References

- [CrossOS Acceleritor GitHub Repository](https://github.com/loscrossos/crossOS_acceleritor)
- [CrossOS Setup](https://github.com/loscrossos/crossos_setup) - Automated AI development environment setup 