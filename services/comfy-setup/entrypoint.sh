#!/usr/bin/env bash

set -Eeuo pipefail

mkdir -vp /data/embeddings \
  /data/config/ \
  /data/models/ \
  /data/models/Stable-diffusion \
  /data/models/GFPGAN \
  /data/models/RealESRGAN \
  /data/models/LDSR \
  /data/models/VAE

 if [[ "$SETUP_DRY_RUN" -eq 1 ]]; then
  echo "Running Dry Run..."

  aria2c --dry-run -x 10 --disable-ipv6 --input-file  ./model.manifest --dir /data/models --continue

else
  echo "Downloading, this might take a while..."

  aria2c -x 10 --disable-ipv6 --input-file ./model.manifest --dir /data/models --continue

  echo "Checking SHAs..."

  parallel --will-cite -a ./checksums.sha256 "echo -n {} | sha256sum -c"
fi

# https://github.com/Comfy-Org/comfy-cli
# Can we use CLI to setup comfy.
# Can the CLI install extnesions or does the manager have a way to do that via CLI?
# Can we use the maninfest format for the CLI?
# -extensions 
# --ipadapter
# ---requirements.txt
# ---model.manifest
# --comfyui-manager
# Or should we do it by "packs"? slim, mega, etc


exec "$@"