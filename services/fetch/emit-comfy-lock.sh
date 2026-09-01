#!/bin/sh
# Render packages down to the `models:` section of a comfy-lock.yaml.
#
# Packages are the authoring format: they carry a sha256 and every known source
# for each file. comfy-lock is the ecosystem-compatible projection of that --
# model, url, paths -- and is therefore GENERATED, never hand-edited.
#
# The downgrade is lossy by design. comfy-lock has no field for a content hash,
# so what it cannot express is dropped rather than smuggled into a comment. What
# survives is exactly what comfy-cli and friends can consume.
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

# One line per file: <install-path> <TAB> <basename> <TAB> <url>. Sorting on the
# first field gives a stable document regardless of the order packages declare
# their models in.
#
# Field-per-line extraction, then joined here -- yq 4.47 emits "\t" in an
# expression literally where 4.53 interprets it, so no escape may appear inside
# the expression itself.
EXPR='.models[].files[] | (["F", .path, ((.sources // [])[0].url // "")]) | .[]'

for dir in "$@"; do
  for pkg in "$dir"/*.yaml "$dir"/*.yml; do
    [ -f "$pkg" ] || continue
    [ "$(yq -r 'has("package")' "$pkg")" = "true" ] || continue
    [ "$(yq -r '.references_only // false' "$pkg")" = "true" ] && continue
    yq -r "$EXPR" "$pkg" | while read -r marker; do
      [ "$marker" = "F" ] || { echo "record desync in $pkg" >&2; exit 3; }
      read -r path
      read -r url
      # A file with no source cannot appear in a comfy-lock entry, whose whole
      # content is a URL. Reported so it is not silently dropped.
      if [ -z "$url" ]; then
        echo "no source, omitted from comfy-lock: $path" >&2
        continue
      fi
      printf 'models/%s\t%s\t%s\n' "$path" "$(basename "$path")" "$url"
    done >> "$work/rows"
  done
done

[ -s "$work/rows" ] || { echo "no model files found in: $*" >&2; exit 1; }

sort -u "$work/rows" > "$work/sorted"

echo "models:"
while IFS='	' read -r install base url; do
  printf '  - model: %s\n' "$base"
  printf '    url: %s\n' "$url"
  printf '    paths:\n'
  printf '      - path: %s\n' "$install"
done < "$work/sorted"
