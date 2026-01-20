#!/bin/bash
set -e

exec python main.py --listen --port $COMFY_PORT $CLI_ARGS