#!/bin/bash
set -e

# Runtime Lock Override
if [ -n "$COMFY_LOCK_FILE" ]; then
    echo "Runtime Lock File detected: $COMFY_LOCK_FILE"
    if [ -f "$COMFY_LOCK_FILE" ]; then
        echo "Installing/Updating nodes from lock file..."
        python3 /app/install_from_lock.py "$COMFY_LOCK_FILE"
    else
        echo "WARNING: Lock file specified but not found: $COMFY_LOCK_FILE"
    fi
fi

# Show comfy environment
comfy env

# Disable tracking (optional)
comfy tracking disable

# Start ComfyUI with the specified parameters
exec comfy launch -- --listen --port $COMFY_PORT $CLI_ARGS
