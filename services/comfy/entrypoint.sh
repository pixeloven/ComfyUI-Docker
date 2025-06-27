#!/bin/bash

set -e

export BASE_DIRECTORY="/data/config/comfy"
export OUTPUT_DIRECTORY="/output"

# This breaks if not run in the context of docker-compose (may need to document how to run without or otherwise improve how we do vol mounting)
mkdir -vp ${BASE_DIRECTORY}
mkdir -vp ${BASE_DIRECTORY}/temp
mkdir -vp ${BASE_DIRECTORY}/user
mkdir -vp ${BASE_DIRECTORY}/custom_nodes
mkdir -vp ${OUTPUT_DIRECTORY}

# @brian - Why is this here?
# XDG_CACHE_HOME - Set cache outside container
# mkdir -vp /data/.cache
# XDG_CACHE_HOME=/data/.cache
# export XDG_CACHE_HOME

# This is broken
if [ -f "/data/config/comfy/startup.sh" ]; then
  pushd ${APPLICATION_ROOT}
  . /data/config/comfy/startup.sh
  popd
fi

exec "$@"
