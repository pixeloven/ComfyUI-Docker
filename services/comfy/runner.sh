#!/bin/bash
set -e

# Activate virtual environment
source ~/.venv/bin/activate

# Start ComfyUI with the specified parameters
comfy launch -- --listen --port $COMFY_PORT --base-directory $BASE_DIRECTORY --output-directory $OUTPUT_DIRECTORY $CLI_ARG