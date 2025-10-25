# Data Management

How to organize models, workflows, and manage persistent data in ComfyUI Docker.

## Data Directory Structure

All persistent data is stored in the `./data/` directory with subdirectories that map directly to ComfyUI's default structure at `/app/`:

```
data/
├── models/              → /app/models (AI models, checkpoints, LoRAs)
├── custom_nodes/        → /app/custom_nodes (Extensions and plugins)
├── input/               → /app/input (Input images and workflows)
├── output/              → /app/output (Generated images)
├── temp/                → /app/temp (Temporary files)
└── user/                → /app/user (User configs and saved workflows)
```

### Directory Purposes

| Directory | Purpose | Mount Mode |
|-----------|---------|------------|
| `models/` | AI models, checkpoints, LoRAs, VAEs, etc. | Read-only (`:ro`) |
| `custom_nodes/` | Custom node extensions | Read-write (`:rw`) |
| `input/` | Input images and workflow files | Read-write (`:rw`) |
| `output/` | Generated images and results | Read-write (`:rw`) |
| `temp/` | Temporary processing files | Read-write (`:rw`) |
| `user/` | Saved workflows and user settings | Read-write (`:rw`) |

## Model Management

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

**Download models** from:
- [Civitai](https://civitai.com/) - Community models
- [Hugging Face](https://huggingface.co/models?pipeline_tag=text-to-image) - Official models
- [ComfyUI Model Database](https://registry.comfy.org/) - Curated models

**Place models** in the appropriate directory:

```bash
# Example: Download a checkpoint
cd data/models/checkpoints/
wget https://example.com/model.safetensors

# Example: Download a LoRA
cd data/models/loras/
wget https://example.com/lora.safetensors

# Restart not needed - ComfyUI auto-detects new models
```

### Custom Model Paths

Override default model path:

```bash
# Use shared model directory
COMFY_MODEL_PATH=/mnt/shared/models docker compose up -d

# In .env file
COMFY_MODEL_PATH=/mnt/shared/models
```

**Advanced:** Use `data/extra_model_paths.yaml` for additional paths:

```yaml
# data/extra_model_paths.yaml
my_models:
  base_path: /mnt/external/models/
  checkpoints: checkpoints/
  loras: loras/
```

Mount the external path in docker-compose.yml:
```yaml
volumes:
  - /mnt/external/models:/mnt/external/models:ro
```

## Workflow Management

### Save Workflows

Workflows are saved through ComfyUI's web interface and stored in:
```
data/user/default/workflows/
```

**To save:**
1. Click "Save" button in ComfyUI
2. Enter workflow name
3. Workflow saved as `.json` file

### Load Workflows

**From UI:**
1. Click "Load" button in ComfyUI
2. Select workflow from list

**From file:**
1. Drag and drop `.json` file into ComfyUI
2. Or click "Load" and browse files

### Backup Workflows

```bash
# Backup all workflows
cp -r data/user/default/workflows/ ~/backups/comfyui-workflows-$(date +%Y%m%d)

# Backup specific workflow
cp data/user/default/workflows/my-workflow.json ~/backups/
```

### Share Workflows

```bash
# Export workflow
cp data/user/default/workflows/my-workflow.json ~/sharing/

# Import workflow (on different machine)
cp ~/Downloads/shared-workflow.json data/user/default/workflows/
```

## Custom Nodes

### Viewing Installed Nodes

```bash
# List custom nodes directory
ls -la data/custom_nodes/

# Inside container
docker compose exec core-cuda ls -la /app/custom_nodes/
```

### Adding Custom Nodes (Core Mode)

```bash
# Clone into custom_nodes directory
cd data/custom_nodes/
git clone https://github.com/author/ComfyUI-CustomNode.git

# Install dependencies if needed
docker compose exec core-cuda pip install -r /app/custom_nodes/ComfyUI-CustomNode/requirements.txt

# Restart ComfyUI
docker compose restart
```

### Adding Custom Nodes (Complete Mode)

Complete mode includes 13+ pre-installed custom nodes. To add more:

1. **Edit installation script** in `services/comfy/complete/scripts/`
2. **Rebuild the image:**
   ```bash
   docker buildx bake complete-cuda --load
   docker compose up -d
   ```

See [Scripts Guide](scripts.md) for details.

## Storage Customization

### Individual Path Override

Each data directory can be customized independently:

```bash
# Use different paths
COMFY_MODEL_PATH=/mnt/shared/models \
COMFY_OUTPUT_PATH=/mnt/fast-ssd/outputs \
COMFY_CUSTOM_NODE_PATH=./my-nodes \
docker compose up -d
```

### .env Configuration

```bash
# .env file
COMFY_MODEL_PATH=/mnt/shared/models
COMFY_OUTPUT_PATH=/mnt/fast-ssd/outputs
COMFY_INPUT_PATH=./data/input
COMFY_CUSTOM_NODE_PATH=./data/custom_nodes
COMFY_TEMP_PATH=./data/temp
COMFY_USER_PATH=./data/user
```

### File Permissions

Set proper ownership for data directories:

```bash
# Get your user/group ID
id

# Set ownership (replace 1000:1000 with your PUID:PGID)
sudo chown -R 1000:1000 ./data

# Or use current user
sudo chown -R $USER:$USER ./data

# Set proper permissions
chmod -R 755 ./data
```

**Configure in .env:**
```bash
PUID=1000
PGID=1000
```

## Disk Space Management

### Check Disk Usage

```bash
# Check data directory size
du -sh ./data/*

# Check specific subdirectories
du -sh ./data/models/*
du -sh ./data/output/*

# Inside container
docker compose exec core-cuda df -h
```

### Clean Output Files

```bash
# Archive old outputs
tar -czf outputs-backup-$(date +%Y%m%d).tar.gz data/output/
mv outputs-backup-*.tar.gz ~/backups/

# Clear outputs
rm -rf data/output/*
```

### Clean Temp Files

```bash
# Remove temporary files
rm -rf data/temp/*
```

### Remove Unused Models

```bash
# List large files
find data/models/ -type f -size +1G -exec ls -lh {} \;

# Remove unused model
rm data/models/checkpoints/old-model.safetensors
```

## Backup Strategy

### Full Backup

```bash
# Backup entire data directory
tar -czf comfyui-backup-$(date +%Y%m%d).tar.gz data/

# Or rsync to external drive
rsync -av --progress ./data/ /mnt/backup/comfyui-data/
```

### Selective Backup

```bash
# Backup only workflows and settings
tar -czf comfyui-workflows-$(date +%Y%m%d).tar.gz data/user/

# Backup custom nodes
tar -czf comfyui-custom-nodes-$(date +%Y%m%d).tar.gz data/custom_nodes/

# Skip models (usually too large)
```

### Restore from Backup

```bash
# Extract backup
tar -xzf comfyui-backup-20250124.tar.gz

# Or restore specific directory
tar -xzf comfyui-workflows-20250124.tar.gz -C ./

# Restart services
docker compose restart
```

## Migration

### Move to Different Machine

```bash
# On old machine
tar -czf comfyui-data.tar.gz data/
scp comfyui-data.tar.gz newmachine:~/

# On new machine
tar -xzf comfyui-data.tar.gz
docker compose up -d
```

### Share Models Between Instances

```bash
# Use shared model directory
COMFY_MODEL_PATH=/mnt/shared/models docker compose up -d

# Different instances can share models but have separate outputs
```

---

**Next:** [Performance Tuning](performance.md) | **Previous:** [Running Containers](running.md) | [Building Images](building.md)
