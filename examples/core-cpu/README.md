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

## Developing a Node Pack
`docker-compose.dev-pack.yml` mounts a custom node pack's source into the
container. Set its `source` and `target`, then:
```bash
docker compose -f docker-compose.yml -f docker-compose.dev-pack.yml up -d
```
See [Developing a Node Pack](../../docs/user-guides/runtime-contract.md#developing-a-node-pack)
in the runtime contract.
