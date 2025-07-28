#!/bin/bash
set -e

# Initialize conda by sourcing the conda profile
source /opt/conda/etc/profile.d/conda.sh

# Activate conda environment as recommended by ComfyUI documentation
conda activate $CONDA_ENV_NAME

# Show comfy environment
# Show environment
comfy env

# Disable tracking (optional)
comfy tracking disable

# Start ComfyUI with the specified parameters
comfy launch -- --listen --port $COMFY_PORT --base-directory $COMFY_BASE_DIRECTORY --output-directory $COMFY_OUTPUT_DIRECTORY $CLI_ARGS