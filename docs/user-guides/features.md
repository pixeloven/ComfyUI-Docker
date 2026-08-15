# Current ComfyUI Feature Support

Audit date: 2026-08-14. The latest stable ComfyUI release at audit time was
v0.33.1. Repository builds pin that stable source release by default. Scheduled
image publishing resolves the newest upstream stable tag and also publishes mirrored
tags such as `core:cuda-v0.33.1`. Set `COMFYUI_VERSION=master` explicitly when
building a nightly image.

## Release Strategy

The image build uses upstream Git tags directly instead of making `comfy-cli`
the installer. Both ultimately check out the same repository, but a direct
tagged clone keeps the Docker layer smaller, makes the selected source visible
in BuildKit metadata, and lets the image resolve the accelerator-specific
PyTorch channel before installing ComfyUI requirements.

`comfy-cli` remains valuable for interactive installation, snapshots, models,
workflow execution, dependency compilation, and version switching. Those are
mutable workspace operations, whereas a published container should be replaced
or rolled back by image tag or digest. This split avoids updating application
source inside a running container and then losing it at the next replacement.

## What the Ecosystem Now Includes

ComfyUI is no longer only a Stable Diffusion image graph. Current upstream
supports native image, video, audio, 3D, text/LLM, training, and model utility
workflows. Its frontend now includes App Mode, Nodes 2.0, subgraphs, workflow
templates, partial execution, embedded node documentation, job progress, and an
Assets sidebar. Closed-source models are exposed as opt-in Partner Nodes, while
custom nodes are distributed through the Comfy Registry and current Manager.

## Container Support Matrix

| Capability | Status | Container behavior |
|---|---|---|
| Current core nodes and model formats | Supported | Upstream source and every current requirement are installed together |
| Frontend, templates, embedded docs | Supported | Versioned packages come from upstream `requirements.txt` |
| App Mode, Nodes 2.0, subgraphs | Supported | No container-specific flags required |
| Video and audio I/O | Supported | PyAV plus system FFmpeg are installed |
| Native LoRA training | Supported | `/app/datasets` is persistent |
| Assets sidebar/index | Enabled | `--enable-assets`; SQLite index persists under `/app/user` |
| Asset content hashing | Opt-in | Add `--enable-asset-hashing` to `CLI_ARGS` for portable hashes |
| ComfyUI Manager | Enabled | Official `comfyui_manager` package and registry UI |
| Partner Nodes | Supported | Outbound network and Comfy account/API-key authentication are required |
| Server API and jobs API | Supported | Port 8188 by default; all upstream endpoints are unmodified |
| Multi-user storage | Opt-in | Add `--multi-user` to `CLI_ARGS` |
| Dynamic VRAM / async offload | Enabled upstream | Add headroom or disable flags only when needed |
| Comfy Kitchen attention | Opt-in | Add `--use-ck-attention` to `CLI_ARGS` |
| MCP automation | Separate image | Build/run the `mcp` target and point `COMFYUI_URL` at this service |

## Hardware Matrix

| Hardware | Image tag | Upstream runtime |
|---|---|---|
| NVIDIA GPU | `core:cuda-latest`, `complete:cuda-latest` | CUDA 13.0 / PyTorch cu130 |
| AMD GPU on Linux | `core:rocm-latest` | PyTorch ROCm 7.2 |
| Intel GPU on Linux | `core:xpu-latest` | PyTorch XPU |
| CPU | `core:cpu-latest` | PyTorch CPU |

Apple Metal, Windows DirectML, AMD Windows wheels, Ascend, and Cambricon remain
native/manual-install paths rather than Linux container targets. Containers do
not virtualize those host driver stacks safely or uniformly.

## Partner Nodes and Remote Access

Partner Nodes are present unless `--disable-api-nodes` is set. Browser account
login works directly on localhost. For LAN or non-whitelisted origins, use a
Comfy account API key; for public deployments, terminate TLS at a reverse proxy
or supply `--tls-keyfile` and `--tls-certfile`. Do not publish an unauthenticated
ComfyUI port directly to the internet.

Headless clients can place `api_key_comfy_org` in the prompt request's
`extra_data`. This is intentionally not represented as a container environment
variable, which avoids putting a paid-service credential into process metadata.

## Persistence Contract

ComfyUI runs with `/app` as its base directory. The examples persist models,
custom nodes, datasets, input, output, temp, and user state at that same base.
This also preserves Manager state, workflows, settings, Partner Node login
state, and the Assets database across image replacement.

## Sources

- [Official documentation index](https://docs.comfy.org/llms.txt)
- [ComfyUI releases](https://github.com/Comfy-Org/ComfyUI/releases)
- [Manual installation and hardware backends](https://docs.comfy.org/installation/manual_install)
- [Partner Nodes](https://docs.comfy.org/tutorials/partner-nodes/overview)
- [ComfyUI Manager](https://docs.comfy.org/manager/overview)
- [comfy-cli](https://github.com/Comfy-Org/comfy-cli)
