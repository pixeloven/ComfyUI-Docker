# ComfyUI Core - GPU

## Overview
This example starts the **Core** ComfyUI image in **GPU (CUDA)** mode.

**Use Case:**
- Standard minimal installation.
- Base for building custom environments.

## Prerequisite
- NVIDIA GPU with drivers installed.
- NVIDIA Container Toolkit installed.

## Usage
```bash
cp .env.example .env
docker compose up -d
```
Access ComfyUI at `http://localhost:8188`.
