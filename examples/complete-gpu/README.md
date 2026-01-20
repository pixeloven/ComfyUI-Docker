# ComfyUI Complete - GPU

## Overview
This example starts the **Complete** ComfyUI image in **GPU (CUDA)** mode.

**Use Case:**
- Full-featured environment.
- Pre-installed system & Python dependencies for heavy nodes (e.g. SageAttention modules/wheels).
- **Does NOT** include pre-installed custom nodes (use Runtime Lock for that).

## Prerequisite
- NVIDIA GPU with drivers installed.
- NVIDIA Container Toolkit installed.

## Usage
```bash
cp .env.example .env
docker compose up -d
```
Access ComfyUI at `http://localhost:8188`.
