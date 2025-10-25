# Data Management

Understanding the data directory structure and how to organize models, workflows, and custom nodes.

## Directory Structure

All persistent data is stored in `./data/` with subdirectories that map to ComfyUI's structure at `/app/`:

```
data/
├── models/              → /app/models (AI models, checkpoints, LoRAs)
├── custom_nodes/        → /app/custom_nodes (Extensions and plugins)
├── input/               → /app/input (Input images and workflows)
├── output/              → /app/output (Generated images)
├── temp/                → /app/temp (Temporary files)
└── user/                → /app/user (User configs and saved workflows)
```

### Mount Modes

| Directory | Purpose | Mount Mode |
|-----------|---------|------------|
| `models/` | AI models, checkpoints, LoRAs, VAEs | Read-only (`:ro`) |
| `custom_nodes/` | Custom node extensions | Read-write (`:rw`) |
| `input/` | Input images and workflow files | Read-write (`:rw`) |
| `output/` | Generated images and results | Read-write (`:rw`) |
| `temp/` | Temporary processing files | Read-write (`:rw`) |
| `user/` | Saved workflows and settings | Read-write (`:rw`) |

## Model Organization

### Model Directory Structure

ComfyUI expects models in specific subdirectories under `data/models/`:

```
data/models/
├── checkpoints/         # Stable Diffusion checkpoints (.safetensors, .ckpt)
├── loras/              # LoRA files
├── vae/                # VAE models
├── embeddings/         # Text embeddings (Textual Inversion)
├── controlnet/         # ControlNet models
├── clip/               # CLIP models
├── clip_vision/        # CLIP vision models
├── upscale_models/     # Upscaling models (ESRGAN, etc.)
├── style_models/       # Style transfer models
└── ipadapter/          # IP-Adapter models
```

### Adding Models

**Download from:**
- [Civitai](https://civitai.com/) - Community models
- [Hugging Face](https://huggingface.co/models?pipeline_tag=text-to-image) - Official models
- [ComfyUI Model Database](https://registry.comfy.org/) - Curated models

**Place in appropriate directory:**
```bash
# Example: Add a checkpoint
data/models/checkpoints/my-model.safetensors

# Example: Add a LoRA
data/models/loras/my-lora.safetensors

# ComfyUI auto-detects new models (no restart needed)
```

## Workflows

### Location

Workflows are saved as JSON files in:
```
data/user/default/workflows/
```

### Save & Load

- **Save**: Click "Save" in ComfyUI interface → enter name → stored as `.json`
- **Load**: Click "Load" button or drag-and-drop `.json` file into interface

### Backup & Share

```bash
# Backup workflows
cp -r data/user/default/workflows/ ~/backups/workflows-$(date +%Y%m%d)

# Share workflow
cp data/user/default/workflows/my-workflow.json ~/shared/
```

## Custom Nodes

### Location

Custom nodes are installed in:
```
data/custom_nodes/
```

### Core Mode

Install manually by cloning into the directory:
```bash
cd data/custom_nodes/
git clone https://github.com/author/ComfyUI-CustomNode.git
```

Then restart the container (see [Running Containers](running.md)).

### Complete Mode

Complete mode includes 13+ pre-installed custom nodes. See [Scripts Guide](scripts.md) for the full list.

## Custom Paths

Override default paths using environment variables. See [Running Containers](running.md) for configuration details.

**Example environment variables:**
```bash
COMFY_MODEL_PATH=/mnt/shared/models
COMFY_OUTPUT_PATH=/mnt/fast-ssd/outputs
COMFY_CUSTOM_NODE_PATH=./my-nodes
```

### Advanced: Extra Model Paths

For additional model paths, create `data/extra_model_paths.yaml`:

```yaml
my_models:
  base_path: /mnt/external/models/
  checkpoints: checkpoints/
  loras: loras/
```

Then mount the path in docker-compose.yml:
```yaml
volumes:
  - /mnt/external/models:/mnt/external/models:ro
```

## File Permissions

Data directories use the user/group ID specified by `PUID` and `PGID` environment variables (default: 1000:1000).

**To set ownership:**
```bash
# Use your user ID
id  # Shows your PUID and PGID

# Set in .env file
PUID=1000
PGID=1000
```

**Fix existing permissions:**
```bash
sudo chown -R $USER:$USER ./data
chmod -R 755 ./data
```

---

**See Also:**
- [Running Containers](running.md) - Configure paths via environment variables
- [Building Images](building.md) - Build with custom configurations
- [Performance Tuning](performance.md) - Optimize storage for performance
