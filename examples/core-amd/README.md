# Core AMD (ROCm)

Linux deployment for supported AMD GPUs using the upstream PyTorch ROCm 7.2
wheels. The host must expose `/dev/kfd` and `/dev/dri`.

```bash
cp .env.example .env
# Adjust VIDEO_GID and RENDER_GID to match the host, then:
docker compose up -d
```

See the official [ComfyUI manual installation hardware notes](https://docs.comfy.org/installation/manual_install)
for the current supported GPU generations and optional compatibility settings.
