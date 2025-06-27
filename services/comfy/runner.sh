#!/bin/bash

set -e

python -u main.py --listen --port 8188 --base-directory $BASE_DIRECTORY --output-directory $OUTPUT_DIRECTORY $CLI_ARGS