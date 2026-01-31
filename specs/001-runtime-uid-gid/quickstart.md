# Quickstart: Runtime UID/GID Support

**Feature**: 001-runtime-uid-gid

## Overview

Run ComfyUI Docker containers with any user/group ID to match your host system, eliminating permission issues with mounted volumes.

## Usage

### Basic Usage (Custom UID/GID)

```bash
# Run with your host user's UID/GID
PUID=$(id -u) PGID=$(id -g) docker compose up -d
```

### Docker Compose Configuration

Add to your `docker-compose.yml`:

```yaml
services:
  comfyui:
    image: ghcr.io/pixeloven/comfyui/core:cuda-latest
    environment:
      - PUID=${PUID:-1000}
      - PGID=${PGID:-1000}
    volumes:
      - ./data/models:/app/models
      - ./data/output:/app/output
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PUID` | `1000` | User ID for running the application |
| `PGID` | `1000` | Group ID for running the application |

### Common Scenarios

**Scenario 1: Match Host User**
```bash
# Find your UID/GID
id -u  # e.g., 1000
id -g  # e.g., 1000

# Set in .env file
echo "PUID=$(id -u)" >> .env
echo "PGID=$(id -g)" >> .env

# Start container
docker compose up -d
```

**Scenario 2: Shared Server (Specific UID)**
```bash
# Run as UID 3000
PUID=3000 PGID=3000 docker compose up -d
```

**Scenario 3: Default Behavior (No Configuration)**
```bash
# Container runs as UID 1000:GID 1000 (unchanged from before)
docker compose up -d
```

## Verification

### Check Container User

```bash
# Verify the running user
docker exec comfyui id
# Expected: uid=3000(comfy) gid=3000(comfy) groups=3000(comfy)
```

### Check File Ownership

```bash
# Create a test file from container
docker exec comfyui touch /app/output/test.txt

# Check ownership on host
ls -la ./data/output/test.txt
# Expected: owned by your specified PUID:PGID
```

### Check Startup Log

```bash
docker logs comfyui | head -1
# Expected: Starting with UID:GID = 3000:3000
```

## Troubleshooting

### Error: Invalid PUID/PGID

```
ERROR: Invalid PUID value 'abc'. Must be a positive integer.
```

**Solution**: Ensure PUID and PGID are valid positive integers.

### Warning: Running as Root

```
WARNING: Running as root (PUID=0). This is not recommended.
```

**Solution**: Use a non-root UID for security. Only use PUID=0 if absolutely necessary.

### Permission Denied on Volumes

If you see permission errors on mounted volumes:

1. Check that PUID/PGID matches your host user
2. Ensure the host directories exist and are writable
3. The container only adjusts /app directory permissions, not mounted volumes

```bash
# Fix host directory ownership
sudo chown -R $(id -u):$(id -g) ./data/
```

## Testing Checklist

- [ ] Container starts with default PUID/PGID (no env vars)
- [ ] Container starts with custom PUID/PGID (e.g., 3000:3000)
- [ ] Files created in mounted volumes have correct ownership
- [ ] No `getpwuid` errors during PyTorch initialization
- [ ] Startup log shows correct UID:GID
- [ ] Process list shows non-root user (except init phase)
