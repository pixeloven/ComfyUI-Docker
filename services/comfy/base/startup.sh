#!/bin/bash
set -e

# Check if post-install steps have already been run
echo "Checking if post install steps have already been run"
if [ -f .post_install_done ]; then
    echo "Post-install steps already completed."
else
    echo "Post-install steps not completed."
    
    # Loop through scripts directory and run scripts in order
    echo "Running post install steps..."
    for script in ./scripts/*.sh; do
        if [ -f "$script" ]; then
            echo "Running: $script"
            "$script"
        fi
    done

    # Mark completion
    touch .post_install_done

    echo "Post-install steps completed successfully."
fi

# Show comfy environment
comfy env

# Disable tracking (optional)
comfy tracking disable

# Start ComfyUI with the specified parameters
comfy launch -- --listen --port $COMFY_PORT --base-directory $COMFY_BASE_DIRECTORY --output-directory $COMFY_OUTPUT_DIRECTORY $CLI_ARGS