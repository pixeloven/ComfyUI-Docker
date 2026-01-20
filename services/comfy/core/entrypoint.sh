#!/bin/bash
set -e

# Activate Python virtual environment
source /app/.venv/bin/activate

exec "$@"
