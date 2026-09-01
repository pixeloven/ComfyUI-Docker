#!/bin/sh
# Resolve comfy.yaml (intent) into comfy-lock.yaml (resolution).
#
# This is the manifest -> lock step, the same one `npm install` performs: the
# manifest says `hf:owner/repo` at `revision: main`, and the lock records the
# exact commit, the exact URL, and the sha256 of the bytes that commit serves.
#
# It talks to the network and it is NOT idempotent across time: re-resolving a
# moving ref after upstream moves is SUPPOSED to produce a new commit and a new
# hash. That is the point. So this never runs in CI as a drift check -- see
# check-lock.sh, which compares manifest against lock offline.
#
# Resolution needs no credentials, even for gated-download sources: HuggingFace
# returns hashes in headers, and Civitai's model-versions endpoint is public.
# Tokens are needed to FETCH, not to resolve.
#
# Usage: resolve.sh <comfy.yaml>
# Writes a `models:` document to stdout. Redirect it into the lock.

set -eu

LC_ALL=C
export LC_ALL

MANIFEST="${1:?usage: resolve.sh <comfy.yaml>}"
[ -f "$MANIFEST" ] || { echo "no such manifest: $MANIFEST" >&2; exit 2; }

UA="comfyui-fetch/1.0 (+https://github.com/pixeloven/ComfyUI-Docker)"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Field-per-line, no escapes: yq 4.47 emits "\t" in an expression literally
# where 4.53 interprets it.
#
# Absent fields are emitted as "-", never as an empty line. $(...) strips
# TRAILING newlines, so a record whose last fields are empty -- `auth` and
# `sha256` usually are -- loses those lines, `read` then consumes the next
# record's data or hits EOF, and `set -e` kills the loop having emitted
# nothing. A sentinel line after the substitution cannot fix this; the
# stripping happens first.
# shellcheck disable=SC2016  # $m is a yq variable, not a shell one.
EXPR='.models[] as $m | $m.files[] |
  ["F", $m.name, .source, (.file // "-"), (.revision // "main"),
   .install, (.as // "-"), (.type // "-"), (.sha256 // "-")] | .[]'

declared="$(yq -r '[.models[].files[]] | length' "$MANIFEST")"
records=0

hf_head() {  # <repo> <revision> <file>  -> commit<TAB>sha256<TAB>size
  curl -sI -A "$UA" "https://huggingface.co/$1/resolve/$2/$3" \
    | tr -d '\r' \
    | awk 'BEGIN{IGNORECASE=1}
           /^x-repo-commit:/  {c=$2}
           /^x-linked-etag:/  {h=$2; gsub(/"/,"",h)}
           /^x-linked-size:/  {s=$2}
           END{ if (c && h && s) printf "%s\t%s\t%s", c, h, s }'
}

# The `END` sentinel is load-bearing. $(...) strips TRAILING newlines, so a
# record whose last fields are empty -- `auth` and `sha256` are optional and
# usually are -- loses those lines entirely, `read` hits EOF mid-record, and
# `set -e` kills the loop silently having emitted nothing.
while read -r marker; do
  [ "$marker" = "END" ] && break
  [ "$marker" = "F" ] || { echo "record desync at '$marker'" >&2; exit 3; }
  read -r capability; read -r source; read -r file; read -r revision
  read -r install; read -r as; read -r type; read -r sha
  records=$((records + 1))
  # "-" is the absent marker the extractor emits; turn it back into empty.
  [ "$file" = "-" ] && file=""
  [ "$as"   = "-" ] && as=""
  [ "$type" = "-" ] && type=""
  [ "$sha"  = "-" ] && sha=""
  :

  case "$source" in
    hf:*)
      repo="${source#hf:}"
      [ -n "$file" ] || { echo "hf source needs \`file\`: $source" >&2; exit 1; }
      got="$(hf_head "$repo" "$revision" "$file")"
      [ -n "$got" ] || { echo "could not resolve hf:$repo@$revision/$file" >&2; exit 1; }
      commit="$(printf '%s' "$got" | cut -f1)"
      sha="$(printf '%s' "$got" | cut -f2)"
      size="$(printf '%s' "$got" | cut -f3)"
      # The lock pins the COMMIT, never the moving ref it was resolved from.
      url="https://huggingface.co/$repo/resolve/$commit/$file"
      base="$(basename "$file")"
      ;;
    civitai:*)
      id="${source#civitai:}"
      curl -sf -A "$UA" "https://civitai.com/api/v1/model-versions/$id" > "$work/cv.json" \
        || { echo "could not resolve $source" >&2; exit 1; }
      url="$(yq -p json -o yaml -r '.files[0].downloadUrl' "$work/cv.json")"
      sha="$(yq -p json -o yaml -r '.files[0].hashes.SHA256 // ""' "$work/cv.json" | tr '[:upper:]' '[:lower:]')"
      size="$(yq -p json -o yaml -r '((.files[0].sizeKB // 0) * 1024) | round' "$work/cv.json")"
      base="$(yq -p json -o yaml -r '.files[0].name' "$work/cv.json")"
      # `if`, not `A && B || C` -- the latter runs C when A is true and B is
      # false, which is not if-then-else and would misreport the reason.
      if [ -z "$sha" ] || [ "$sha" = "null" ]; then
        echo "$source has no SHA256" >&2; exit 1
      fi
      ;;
    gh:*)
      # gh:<owner>/<repo>@<tag>. The asset is `file`.
      spec="${source#gh:}"; repo="${spec%@*}"; tag="${spec##*@}"
      [ -n "$file" ] || { echo "gh source needs \`file\` (the asset name): $source" >&2; exit 1; }
      set --
      if [ -n "${GITHUB_TOKEN:-}" ]; then set -- -H "Authorization: Bearer $GITHUB_TOKEN"; fi
      curl -sf -A "$UA" "$@" "https://api.github.com/repos/$repo/releases/tags/$tag" > "$work/gh.json" \
        || { echo "could not read release $repo@$tag" >&2; exit 1; }
      url="$(ASSET="$file" yq -p json -o yaml -r '.assets[] | select(.name == strenv(ASSET)) | .browser_download_url' "$work/gh.json")"
      if [ -z "$url" ] || [ "$url" = "null" ]; then
        echo "no asset named $file in $repo@$tag" >&2; exit 1
      fi
      size="$(ASSET="$file" yq -p json -o yaml -r '.assets[] | select(.name == strenv(ASSET)) | .size' "$work/gh.json")"
      digest="$(ASSET="$file" yq -p json -o yaml -r '.assets[] | select(.name == strenv(ASSET)) | .digest // ""' "$work/gh.json")"
      if [ -n "$digest" ] && [ "$digest" != "null" ]; then
        sha="${digest#sha256:}"
      elif [ -z "$sha" ]; then
        # GitHub only computes digests for newer uploads, and much of the
        # ComfyUI ecosystem's models sit on releases from 2021. Downloading is
        # the only honest way to learn the hash -- an unverifiable lock entry
        # would defeat the point -- but it is avoidable by stating `sha256` in
        # the manifest.
        echo "no digest for $file in $repo@$tag; downloading to hash it (state \`sha256\` to skip)" >&2
        curl -fsSL -A "$UA" "$url" -o "$work/asset" \
          || { echo "could not download $url" >&2; exit 1; }
        sha="$(sha256sum "$work/asset" | cut -d' ' -f1)"
        rm -f "$work/asset"
      fi
      base="$file"
      ;;
    http://*|https://*)
      # Nothing about a bare URL can be resolved from headers, so the manifest
      # must state the hash. Refusing is the honest outcome: writing a lock
      # entry with no hash would produce a fetch that verifies nothing.
      [ -n "$sha" ] || { echo "direct URL needs \`sha256\` in the manifest: $source" >&2; exit 1; }
      url="$source"
      size="$(curl -sI -A "$UA" "$source" | tr -d '\r' \
              | awk 'BEGIN{IGNORECASE=1} /^content-length:/{print $2}' | tail -1)"
      base="$(basename "${source%%\?*}")"
      ;;
    *) echo "unknown source scheme: $source" >&2; exit 1 ;;
  esac

  if [ -n "$as" ]; then base="$as"; fi
  printf '%s%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$install" "$base" "$base" "$url" "$sha" "${size:-0}" "$type" >> "$work/rows"
  echo "resolved $capability: $base" >&2
done <<EOF
$(yq -r "$EXPR" "$MANIFEST")
END
EOF

# Reading zero records from a manifest that declares files must never be
# reported as success.
if [ "$records" != "$declared" ]; then
  echo "read $records records but the manifest declares $declared files" >&2
  exit 3
fi

sort -u "$work/rows" > "$work/sorted"

# The credential map is copied through verbatim. It lives at the TOP LEVEL of
# the lock, never inside a model entry, so `models[]` stays exactly comfy-cli's
# documented shape.
if [ "$(yq -r 'has("auth")' "$MANIFEST")" = "true" ]; then
  yq -o yaml -r '{"auth": .auth}' "$MANIFEST"
fi

echo "models:"
while IFS='	' read -r install base url sha size type; do
  printf '  - model: %s\n' "$base"
  printf '    url: %s\n' "$url"
  printf '    paths:\n'
  printf '      - path: %s\n' "$install"
  printf '    hashes:\n'
  printf '      - hash: %s\n' "$sha"
  printf '        type: SHA256\n'
  # `if`, not `[ ... ] && ...`: a false test as the LAST command in the loop
  # body makes the body return non-zero, and `set -e` then kills the loop
  # mid-way through -- which is exactly how this silently emitted nothing.
  if [ "$size" != "0" ]; then printf '    size_bytes: %s\n' "$size"; fi
  if [ -n "$type" ]; then printf '    type: %s\n' "$type"; fi
done < "$work/sorted"
