#!/bin/bash
set -e

# Show comfy environment
comfy env

# Disable tracking (optional)
comfy tracking disable

# Start ComfyUI with the specified parameters (uses /app by default)
comfy launch -- --listen --port $COMFY_PORT $CLI_ARGS