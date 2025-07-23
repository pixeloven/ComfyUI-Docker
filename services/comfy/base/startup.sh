#!/bin/bash
set -e

# Activate virtual environment
source ~/.venv/bin/activate

# Show comfy environment
# Show environment
comfy env

# Disable tracking (optional)
comfy tracking disable

# Run SageAttention configuration if available
if [ -f "./scripts/10-sage-attention.sh" ]; then
    echo "🔧 Running SageAttention configuration..."
    ./scripts/10-sage-attention.sh
fi

# Start ComfyUI with the specified parameters
comfy launch -- --listen --port $COMFY_PORT --base-directory $COMFY_BASE_DIRECTORY --output-directory $COMFY_OUTPUT_DIRECTORY $CLI_ARGS