# ComfyUI Core - CPU

## Overview
This example starts the **Core** ComfyUI image in **CPU-only** mode.

**Use Case:**
- Minimal installation.
- Testing on non-GPU hardware.
- CI/CD pipelines.

## Usage
```bash
cp .env.example .env
docker compose up -d
```
Access ComfyUI at `http://localhost:8188`.
