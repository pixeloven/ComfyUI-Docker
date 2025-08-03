#!/bin/bash
set -e

# Activate Python virtual environment
source $VENV_PATH/bin/activate

exec "$@"
