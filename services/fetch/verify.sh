#!/bin/sh
# Build-time acceptance test for the comfyui-fetch image.
#
# Run INSIDE the image, with no bind mounts:
#
#   docker run --rm -i --entrypoint sh <image> -s < verify.sh
#
# Mounts are deliberately avoided. On a DinD/ARC runner the job's own
# filesystem is not the Docker host's, so `-v "$(mktemp -d):/w"` silently
# mounts an empty directory and every fixture vanishes -- which is exactly how
# the first version of this failed with "no such package".
#
# Asserts the three properties the image exists to provide: it fetches the right
# bytes, it does nothing the second time, and it rejects a file whose hash does
# not match -- reporting THAT as the reason.

set -eu

URL=https://huggingface.co/ximso/RealESRGAN_x4plus_anime_6B/resolve/main/RealESRGAN_x4plus_anime_6B.pth
WANT=f872d837d3c90ed2e05227bed711af5671a6fd1c9f7d7e91c911a61f155e99da
BAD=0000000000000000000000000000000000000000000000000000000000000000

mkdir -p /tmp/v/models /tmp/v/m2

pkg() {
  cat <<EOF
package: $1
models:
  - name: verify
    files:
      - path: upscale_models/anime6b.pth
        sha256: "$2"
        sources:
          - kind: huggingface_mirror
            url: $URL
EOF
}

pkg verify "$WANT" > /tmp/v/good.yaml
# Written from the same generator with a different hash, so the negative case
# cannot drift into being a copy of the positive one.
pkg verify-negative "$BAD" > /tmp/v/bad.yaml

echo "--- it fetches, and lands the right bytes ---"
fetch-package.sh /tmp/v/good.yaml /tmp/v/models --apply
got="$(sha256sum /tmp/v/models/upscale_models/anime6b.pth | cut -d' ' -f1)"
[ "$got" = "$WANT" ] || { echo "FETCHED WRONG BYTES: $got"; exit 1; }

echo "--- the second run is a no-op ---"
fetch-package.sh /tmp/v/good.yaml /tmp/v/models --apply | grep -q '^present:     1' \
  || { echo "NOT IDEMPOTENT"; fetch-package.sh /tmp/v/good.yaml /tmp/v/models --apply; exit 1; }

echo "--- a wrong hash fails, for the RIGHT reason ---"
# Asserting only "exit non-zero" is not enough: a full disk or a dead host also
# exits non-zero, so the negative case would pass while proving nothing about
# hash checking. The reason is asserted too.
if fetch-package.sh /tmp/v/bad.yaml /tmp/v/m2 --apply > /tmp/v/neg.log 2>&1; then
  echo "ACCEPTED A FILE THAT DID NOT MATCH ITS HASH"; cat /tmp/v/neg.log; exit 1
fi
grep -q 'sha256 mismatch' /tmp/v/neg.log \
  || { echo "REJECTED, BUT NOT FOR THE HASH:"; cat /tmp/v/neg.log; exit 1; }
[ ! -e /tmp/v/m2/upscale_models/anime6b.pth ] \
  || { echo "LEFT A REJECTED FILE IN THE STORE"; exit 1; }

echo "--- the record parser reads every declared file ---"
# The assertion that makes the yq-escape class of silent pass impossible.
pkg verify "$WANT" > /tmp/v/one.yaml
fetch-package.sh /tmp/v/one.yaml /tmp/v/models | grep -qE '^(present|would fetch): *1' \
  || { echo "PARSER READ NOTHING"; exit 1; }

echo "verify ok: fetches, is idempotent, rejects a hash mismatch, and parses records"
