# ComfyUI Complete - GPU

## Overview
This example starts the **Complete** ComfyUI image in **GPU (CUDA)** mode.

**Use Case:**
- Full-featured environment.
- Pre-installed system and Python dependencies shared by common custom nodes.
- ComfyUI's maintained Comfy Kitchen attention backend is available with
  `CLI_ARGS=--use-ck-attention`.
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
