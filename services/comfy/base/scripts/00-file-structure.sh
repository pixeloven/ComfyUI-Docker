#!/bin/bash
set -e

# @todo these warning checks should probably done in the entrypoint.sh script. consider organizing the scripts into categories such as "pre-install", "post-install", "startup", "entrypoint", etc.
# Set default values for environment variables
if [ -z "$COMFY_PORT" ]; then
    echo "[WARNING] COMFY_PORT is not set, using default 8188"
    COMFY_PORT=8188
fi

if [ -z "$COMFY_BASE_DIRECTORY" ]; then
    echo "[WARNING] COMFY_BASE_DIRECTORY is not set, using default /data/config/comfy"
    COMFY_BASE_DIRECTORY="/data/config/comfy"
fi

if [ ! -d "${COMFY_BASE_DIRECTORY}" ]; then
    mkdir -vp ${COMFY_BASE_DIRECTORY}
fi

if [ -z "$COMFY_OUTPUT_DIRECTORY" ]; then
    echo "[WARNING] COMFY_OUTPUT_DIRECTORY is not set, using default /output"
    COMFY_OUTPUT_DIRECTORY="/output"
fi

if [ ! -d "${COMFY_OUTPUT_DIRECTORY}" ]; then
    mkdir -vp ${COMFY_OUTPUT_DIRECTORY}
fi