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

  aria2c --dry-run -x 10 --disable-ipv6 --input-file ./links.txt --dir /data/models --continue

else
  echo "Downloading, this might take a while..."

  aria2c -x 10 --disable-ipv6 --input-file ./links.txt --dir /data/models --continue

  echo "Checking SHAs..."

  parallel --will-cite -a ./checksums.sha256 "echo -n {} | sha256sum -c"
fi

exec "$@"