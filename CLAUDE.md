# ComfyUI-Docker Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-01-30

## Active Technologies
- Python 3.12, Dockerfile syntax, Bash scripts + PyTorch 2.8+, CUDA 12.9.1, sageattention 2.2.0, sageattn3 3.0.0 (002-sage-attention-update)
- N/A (package installation only) (002-sage-attention-update)

- Bash (entrypoint scripts), Dockerfile syntax + gosu (privilege dropping), standard Linux utilities (groupadd, useradd, getent, chown) (001-runtime-uid-gid)

## Project Structure

```text
src/
tests/
```

## Commands

# Add commands for Bash (entrypoint scripts), Dockerfile syntax

## Code Style

Bash (entrypoint scripts), Dockerfile syntax: Follow standard conventions

## Recent Changes
- 002-sage-attention-update: Added Python 3.12, Dockerfile syntax, Bash scripts + PyTorch 2.8+, CUDA 12.9.1, sageattention 2.2.0, sageattn3 3.0.0

- 001-runtime-uid-gid: Added Bash (entrypoint scripts), Dockerfile syntax + gosu (privilege dropping), standard Linux utilities (groupadd, useradd, getent, chown)

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
