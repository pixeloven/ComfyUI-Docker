#!/bin/bash

set -e

python -u main.py --listen --port $COMFY_PORT --base-directory $BASE_DIRECTORY --output-directory $OUTPUT_DIRECTORY $CLI_ARGS