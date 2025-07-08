#!/bin/bash
set -e

# Activate virtual environment
source ~/.venv/bin/activate

# Set default values for environment variables
if [ -z "$COMFY_PORT" ]; then
    echo "[WARNING] COMFY_PORT is not set, using default 8188"
    COMFY_PORT=8188
fi

if [ -z "$BASE_DIRECTORY" ]; then
    echo "[WARNING] BASE_DIRECTORY is not set, using default /data/config/comfy"
    BASE_DIRECTORY="/data/config/comfy"
fi

if [ ! -d "${BASE_DIRECTORY}" ]; then
    mkdir -vp ${BASE_DIRECTORY}
fi

if [ -z "$OUTPUT_DIRECTORY" ]; then
    echo "[WARNING] OUTPUT_DIRECTORY is not set, using default /output"
    OUTPUT_DIRECTORY="/output"
fi

if [ ! -d "${OUTPUT_DIRECTORY}" ]; then
    mkdir -vp ${OUTPUT_DIRECTORY}
fi

# Show environment
comfy env

# Disable tracking (optional)
comfy tracking disable

# Install custom nodes from comfy-lock.yaml file if it exists
if [ -f "comfy-lock.yaml" ]; then
    echo "Installing custom nodes from comfy-lock.yaml..."
    comfy node install-deps --deps=comfy-lock.yaml
else
    echo "No comfy-lock.yaml or comfy-lock.json found, skipping custom node installation"
fi

# Start ComfyUI with the specified parameters
comfy launch -- --listen --port $COMFY_PORT --base-directory $BASE_DIRECTORY --output-directory $OUTPUT_DIRECTORY $CLI_ARG