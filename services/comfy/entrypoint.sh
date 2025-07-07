#!/bin/bash
set -e

mkdir -vp ${BASE_DIRECTORY}
mkdir -vp ${BASE_DIRECTORY}/temp
mkdir -vp ${BASE_DIRECTORY}/user
mkdir -vp ${BASE_DIRECTORY}/custom_nodes
mkdir -vp ${OUTPUT_DIRECTORY}

exec "$@"
