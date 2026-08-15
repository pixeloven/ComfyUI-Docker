# Core Intel (XPU)

Linux deployment for Intel Arc GPUs using the upstream PyTorch XPU wheels. The
host must expose `/dev/dri` and have a current Intel compute runtime and driver.

```bash
cp .env.example .env
# Adjust VIDEO_GID and RENDER_GID to match the host, then:
docker compose up -d
```

Use `CLI_ARGS=--oneapi-device-selector=...` when a host has multiple Intel
devices and a specific selector is required.
