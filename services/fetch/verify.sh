#!/bin/sh
# Build-time acceptance test for the fetch image.
#
# Run INSIDE the image, with no bind mounts:
#
#   docker run --rm -i --entrypoint sh <image> -s < verify.sh
#
# Mounts are deliberately avoided. On a DinD runner the job's filesystem is not
# the Docker host's, so `-v "$(mktemp -d):/w"` silently mounts an empty
# directory and every fixture vanishes.
#
# Asserts the properties the image exists to provide: it fetches the right
# bytes, it does nothing the second time, it rejects a file whose hash does not
# match AND says that is why, it refuses an entry it cannot verify at all, and
# its record parser reads every model the lock declares.

set -eu

URL=https://huggingface.co/ximso/RealESRGAN_x4plus_anime_6B/resolve/main/RealESRGAN_x4plus_anime_6B.pth
WANT=f872d837d3c90ed2e05227bed711af5671a6fd1c9f7d7e91c911a61f155e99da
BAD=0000000000000000000000000000000000000000000000000000000000000000

mkdir -p /tmp/v/root /tmp/v/r2 /tmp/v/r3

lock() {  # <sha256-or-empty>
  echo "models:"
  echo "  - model: anime6b.pth"
  echo "    url: $URL"
  echo "    paths:"
  echo "      - path: models/upscale_models/anime6b.pth"
  if [ -n "$1" ]; then
    echo "    hashes:"
    echo "      - hash: $1"
    echo "        type: SHA256"
  fi
  echo "    type: upscale_model"
}

lock "$WANT" > /tmp/v/good.yaml
lock "$BAD"  > /tmp/v/bad.yaml
lock ""      > /tmp/v/nohash.yaml

echo "--- it fetches, and lands the right bytes ---"
fetch-lock.sh /tmp/v/good.yaml /tmp/v/root --apply
got="$(sha256sum /tmp/v/root/models/upscale_models/anime6b.pth | cut -d' ' -f1)"
[ "$got" = "$WANT" ] || { echo "FETCHED WRONG BYTES: $got"; exit 1; }

echo "--- the second run is a no-op ---"
fetch-lock.sh /tmp/v/good.yaml /tmp/v/root --apply | grep -q '^present:     1' \
  || { echo "NOT IDEMPOTENT"; fetch-lock.sh /tmp/v/good.yaml /tmp/v/root --apply; exit 1; }

echo "--- a wrong hash fails, for the RIGHT reason ---"
# Asserting only "exit non-zero" is not enough: a full disk or a dead host also
# exits non-zero, so the negative case would pass while proving nothing about
# hash checking. The reason is asserted too.
if fetch-lock.sh /tmp/v/bad.yaml /tmp/v/r2 --apply > /tmp/v/neg.log 2>&1; then
  echo "ACCEPTED A FILE THAT DID NOT MATCH ITS HASH"; cat /tmp/v/neg.log; exit 1
fi
grep -q 'sha256 mismatch' /tmp/v/neg.log \
  || { echo "REJECTED, BUT NOT FOR THE HASH:"; cat /tmp/v/neg.log; exit 1; }
[ ! -e /tmp/v/r2/models/upscale_models/anime6b.pth ] \
  || { echo "LEFT A REJECTED FILE IN THE STORE"; exit 1; }

echo "--- an entry with no hash is refused, not fetched unverified ---"
fetch-lock.sh /tmp/v/nohash.yaml /tmp/v/r3 --apply > /tmp/v/nh.log 2>&1
grep -q 'no SHA256 in the lock' /tmp/v/nh.log \
  || { echo "DID NOT REFUSE AN UNVERIFIABLE ENTRY:"; cat /tmp/v/nh.log; exit 1; }
[ ! -e /tmp/v/r3/models/upscale_models/anime6b.pth ] \
  || { echo "FETCHED AN ENTRY IT COULD NOT VERIFY"; exit 1; }

echo "--- a mapped-but-unset credential must not block a PUBLIC file ---"
# Behaviour that changed when credentials moved from a per-entry `auth` field
# to a host-keyed map: a host can be listed in `auth` while most of its files
# are public. Refusing them because the variable happens to be unset would be
# wrong, so the credential is recorded and only NAMED if the fetch then fails.
mkdir -p /tmp/v/r4
{ echo "auth:"; echo "  huggingface.co: \${HF_TOKEN}"; lock "$WANT"; } > /tmp/v/authmap.yaml
( unset HF_TOKEN; fetch-lock.sh /tmp/v/authmap.yaml /tmp/v/r4 --apply ) > /tmp/v/am.log 2>&1 || {
  echo "A MAPPED-BUT-UNSET CREDENTIAL BLOCKED A PUBLIC FILE:"; cat /tmp/v/am.log; exit 1
}
[ -f /tmp/v/r4/models/upscale_models/anime6b.pth ] \
  || { echo "PUBLIC FILE NOT FETCHED UNDER AN AUTH MAP"; cat /tmp/v/am.log; exit 1; }

echo "--- the record parser reads every model the lock declares ---"
# The assertion that makes the yq-escape class of silent pass impossible.
fetch-lock.sh /tmp/v/good.yaml /tmp/v/root | grep -qE '^(present|would fetch): *1' \
  || { echo "PARSER READ NOTHING"; exit 1; }

echo "verify ok: fetches, idempotent, rejects a mismatch, refuses the unverifiable, honours the auth map, parses records"
