#!/bin/sh
# Render packages down to the `models:` section of a comfy-lock.yaml.
#
# Packages are the authoring format. comfy-lock is the ecosystem-compatible
# projection of them, and is therefore GENERATED, never hand-edited.
#
# The projection carries the content hash. comfy-cli's documented format has a
# `hashes:` block -- a list of {hash, type} with type in AutoV1, AutoV2, SHA256,
# CRC32, Blake3 -- so the sha256 a package records survives into comfy-lock
# rather than being dropped. (Its current IMPLEMENTATION writes a singular
# scalar `hash` instead, and never populates models at all, so the README is the
# only contract that exists to target.)
#
# What does not survive is everything a package knows that comfy-lock cannot
# express: additional ranked sources, credential kinds, install roles beyond the
# `type` field, file sizes. Those are dropped rather than smuggled into a
# comment.
#
# Output is sorted by install path so the result is byte-stable and a drift gate
# can diff it.
#
# Usage: emit-comfy-lock.sh <packages-dir> [...]
# Writes a `models:` document to stdout.

set -eu

LC_ALL=C
export LC_ALL

[ "$#" -gt 0 ] || { echo "usage: emit-comfy-lock.sh <packages-dir> [...]" >&2; exit 2; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Field-per-line extraction: yq 4.47 emits "\t" inside an expression literally
# where 4.53 interprets it, so no escape may appear in the expression itself.
# `.models[] as $m` carries the model's role down to each of its files.
# shellcheck disable=SC2016  # $m is a yq variable, not a shell one.
EXPR='.models[] as $m | $m.files[] |
  ["F", .path, (.sha256 // ""), ((.sources // [])[0].url // ""), ($m.role // "")] | .[]'

for dir in "$@"; do
  for pkg in "$dir"/*.yaml "$dir"/*.yml; do
    [ -f "$pkg" ] || continue
    [ "$(yq -r 'has("package")' "$pkg")" = "true" ] || continue
    [ "$(yq -r '.references_only // false' "$pkg")" = "true" ] && continue
    yq -r "$EXPR" "$pkg" | while read -r marker; do
      [ "$marker" = "F" ] || { echo "record desync in $pkg" >&2; exit 3; }
      read -r path
      read -r sha
      read -r url
      read -r role
      # A file with no source cannot appear in a comfy-lock entry, whose whole
      # content is a URL. Reported so it is not silently dropped.
      if [ -z "$url" ]; then
        echo "no source, omitted from comfy-lock: $path" >&2
        continue
      fi
      printf 'models/%s\t%s\t%s\t%s\t%s\n' \
        "$path" "$(basename "$path")" "$url" "$sha" "$role"
    done >> "$work/rows"
  done
done

[ -s "$work/rows" ] || { echo "no model files found in: $*" >&2; exit 1; }

sort -u "$work/rows" > "$work/sorted"

echo "models:"
while IFS='	' read -r install base url sha role; do
  printf '  - model: %s\n' "$base"
  printf '    url: %s\n' "$url"
  printf '    paths:\n'
  printf '      - path: %s\n' "$install"
  if [ -n "$sha" ]; then
    printf '    hashes:\n'
    printf '      - hash: %s\n' "$sha"
    printf '        type: SHA256\n'
  fi
  [ -n "$role" ] && printf '    type: %s\n' "$role"
done < "$work/sorted"
