# Shared Models Directory

This directory contains AI models that are shared between all ComfyUI instances:

- `checkpoints/` - Stable Diffusion checkpoints (.safetensors, .ckpt)
- `vae/` - VAE models for encoding/decoding
- `loras/` - LoRA models for fine-tuning
- `embeddings/` - Textual inversion embeddings
- `controlnet/` - ControlNet models
- `upscale_models/` - Upscaling models (ESRGAN, etc.)

All instances can read from this directory but should not write to it.