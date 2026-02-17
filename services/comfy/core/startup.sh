#!/bin/bash
set -e

exec python main.py --listen --port $COMFY_PORT --enable-manager $CLI_ARGS