# Stable Diffusion WebUI Docker

Run Stable Diffusion on your machine with a nice UI without any hassle!

## Setup & Usage

Visit the wiki for [Setup](https://github.com/AbdBarho/stable-diffusion-webui-docker/wiki/Setup) and [Usage](https://github.com/AbdBarho/stable-diffusion-webui-docker/wiki/Usage) instructions, checkout the [FAQ](https://github.com/AbdBarho/stable-diffusion-webui-docker/wiki/FAQ) page if you face any problems, or create a new issue!

## Features

This repository provides multiple UIs for you to play around with stable diffusion:

### [ComfyUI](https://github.com/comfyanonymous/ComfyUI)

[Full feature list here](https://github.com/comfyanonymous/ComfyUI#features), Screenshot:

| Workflow                                                                         |
| -------------------------------------------------------------------------------- |
| ![](https://github.com/comfyanonymous/ComfyUI/raw/main/comfyui_screenshot.png) |

**CPU Support**: ComfyUI now supports both GPU and CPU-only modes. See [CPU Support Documentation](docs/CPU_SUPPORT.md) for details.

## 🚀 Quick Start

### ComfyUI (Recommended)

```bash
# 1. Clone and setup
git clone https://github.com/AbdBarho/stable-diffusion-webui-docker.git
cd stable-diffusion-webui-docker
cp .env.example .env

# 2. Start ComfyUI (GPU mode)
docker compose --profile comfy up -d

# 3. Open ComfyUI at http://localhost:8188
```

### CPU Mode
```bash
# Configure for CPU-only mode
echo 'COMFY_CLI_ARGS="--cpu"' >> .env
docker compose --profile comfy-cpu up -d
# Open at http://localhost:8189
```

### Model Setup (Optional)
```bash
# Download models (dry run first to preview)
docker compose --profile comfy-setup up

# For actual download, edit .env: SETUP_CLI_ARGS=""
```

## 📚 Documentation

- **[Quick Reference](docs/QUICK_REFERENCE.md)** - Essential commands and troubleshooting
- **[CPU Support Guide](docs/CPU_SUPPORT.md)** - GPU and CPU configuration
- **[Local CI Testing](docs/LOCAL_CI_TESTING.md)** - Test GitHub Actions locally
- **[Documentation Index](docs/README.md)** - All available guides

## Contributing

Contributions are welcome! **Create a discussion first of what the problem is and what you want to contribute (before you implement anything)**

## Disclaimer

The authors of this project are not responsible for any content generated using this interface.

This license of this software forbids you from sharing any content that violates any laws, produce any harm to a person, disseminate any personal information that would be meant for harm, spread misinformation and target vulnerable groups. For the full list of restrictions please read [the license](./LICENSE).

## Shoutout

Special thanks to everyone behind these awesome projects, without them, none of this would have been possible:

- [AbdBarho/stable-diffusion-webui-docker](https://github.com/AbdBarho/stable-diffusion-webui-docker)
- [AUTOMATIC1111/stable-diffusion-webui](https://github.com/AUTOMATIC1111/stable-diffusion-webui)
- [InvokeAI](https://github.com/invoke-ai/InvokeAI)
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
- [CompVis/stable-diffusion](https://github.com/CompVis/stable-diffusion)
- [Sygil-webui](https://github.com/Sygil-Dev/sygil-webui)
- and many many more.
