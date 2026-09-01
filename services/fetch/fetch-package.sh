#!/bin/sh
# Materialise the model files a package declares.
#
# The package format records, for every file, its sha256 and every known source
# ranked best-first. This script is what makes that ranking worth anything: it
# walks the list until one works rather than depending on a single host, and it
# verifies before it commits.
#
# Two properties matter more than speed.
#
#   A fetch is verified, not trusted. A wrong-but-plausible file is worse than a
#   failed one -- it renders subtly wrong images with no error anywhere.
#
#   A partial file is never left in place. Downloads land on a temporary sibling
#   and are renamed only after the hash matches, so an interrupted run leaves the
#   store exactly as it found it.
#
# Dependencies are curl, sha256sum and yq. Any image carrying those three can
# run it, which is the point: this is the fetch step a ComfyUI image or Helm
# chart can ship without imposing a language runtime on its consumers.
#
# Usage: fetch-package.sh <package.yaml> <dest-root> [--apply]
# Dry run unless --apply. Exit 0 if nothing failed, 1 otherwise.

set -eu

PACKAGE="${1:?usage: fetch-package.sh <package.yaml> <dest-root> [--apply]}"
DEST="${2:?usage: fetch-package.sh <package.yaml> <dest-root> [--apply]}"
APPLY="${3:-}"

[ -f "$PACKAGE" ] || { echo "no such package: $PACKAGE" >&2; exit 2; }

case "$APPLY" in
  --apply) DRY=0 ;;
  "")      DRY=1 ;;
  *)       echo "unknown argument: $APPLY" >&2; exit 2 ;;
esac

# Counters, reported explicitly rather than inferred. A run that reported
# "0 fetched, 10 already present" against an EMPTY directory is the exact
# failure this accounting exists to make impossible: "not downloaded" is never
# allowed to read as "already correct".
n_present=0; n_fetched=0; n_skipped=0; n_failed=0; n_would=0; bytes=0

# One record per file, as a flat sequence of one field per line:
#
#   FILE / <path> / <sha256> / <n-sources> / then n * (<auth>, <url>)
#
# No delimiters and no escapes, deliberately. The first version of this used
# "\t"-separated records, which yq 4.53 interprets and yq 4.47 emits LITERALLY --
# so against the pinned image the reader matched nothing, processed zero files
# and exited 0. A count-driven format is identical on both, and the record
# assertion below turns any future variant of that into a loud failure.
EXPR='.models[].files[] |
  (["FILE", .path, (.sha256 // ""), ((.sources // []) | length | tostring)]
   + ((.sources // []) | map([(.auth // "-"), .url]) | flatten))
  | .[]'

# How many files the package declares, checked against how many were read.
declared="$(yq -r '[.models[].files[]] | length' "$PACKAGE")"

# The token an auth kind needs. Absent means the source is SKIPPED, not tried:
# an unauthenticated Civitai request returns an HTML error page with HTTP 200,
# which would be written to disk and then fail the hash check with a message
# naming the wrong cause.
token_for() {
  case "$1" in
    civitai)     printf '%s' "${CIVITAI_TOKEN:-}" ;;
    huggingface) printf '%s' "${HF_TOKEN:-}" ;;
    *)           printf '' ;;
  esac
}

hash_of() { sha256sum "$1" | cut -d' ' -f1; }

path=""; want=""; srcs=""

# A literal newline. `srcs` is built by plain expansion rather than command
# substitution because $(...) strips trailing newlines, which silently glued a
# second source onto the end of the first -- invisible while every package had
# exactly one source, and wrong the moment one did not.
NL="
"

# Fetch the file accumulated in $path/$want/$srcs. Every branch resets the
# accumulator, so a `return` can never leak state into the next record.
flush() {
  [ -n "$path" ] || return 0
  _p="$path"; _w="$want"; _s="$srcs"
  path=""; want=""; srcs=""

  target="$DEST/$_p"

  # Already correct: re-downloading a 20 GB checkpoint to arrive at the same
  # bytes is the most expensive way to do nothing.
  if [ -f "$target" ] && [ -n "$_w" ] && [ "$(hash_of "$target")" = "$_w" ]; then
    n_present=$((n_present + 1)); return 0
  fi

  if [ -z "$_s" ]; then
    echo "  SKIP    $_p: no source recorded (unreconstructible)"
    n_skipped=$((n_skipped + 1)); return 0
  fi

  if [ "$DRY" = 1 ]; then
    n_would=$((n_would + 1)); return 0
  fi

  # A destination that cannot be written is not a source problem. Checked once,
  # before any request, so the error names the real cause -- an earlier run hit
  # a root-owned volume and reported it as four separate SOURCE failures, one
  # per source tried against an unwritable path.
  tmp="$target.fetch-tmp"
  if ! mkdir -p "$(dirname "$target")" 2>/dev/null || ! : > "$tmp" 2>/dev/null; then
    echo "  FAILED  $_p: destination not writable"
    n_failed=$((n_failed + 1)); return 0
  fi

  problems=""; got=0
  # Here-doc, not a pipe: a piped `while` runs in a subshell, where `got` and
  # `problems` would be set and then discarded.
  while IFS='	' read -r auth url; do
    [ -n "$url" ] || continue
    tok="$(token_for "$auth")"
    if [ "$auth" != "-" ] && [ -z "$tok" ]; then
      problems="${problems:+$problems; }$auth: no token"; continue
    fi
    if [ -n "$tok" ]; then set -- -H "Authorization: Bearer $tok"; else set --; fi
    if ! curl -fsSL --retry 3 --retry-delay 2 --connect-timeout 30 "$@" -o "$tmp" "$url"; then
      problems="${problems:+$problems; }$url: transfer failed"; continue
    fi
    if [ -n "$_w" ] && [ "$(hash_of "$tmp")" != "$_w" ]; then
      # A source serving the wrong bytes is worse than one that fails: keep it
      # out of the store and keep going down the list.
      problems="${problems:+$problems; }$url: sha256 mismatch"; continue
    fi
    got=1; break
  done <<INNER
$_s
INNER

  if [ "$got" = 1 ]; then
    sz=$(wc -c < "$tmp")
    mv "$tmp" "$target"
    bytes=$((bytes + sz)); n_fetched=$((n_fetched + 1))
  else
    rm -f "$tmp"
    echo "  FAILED  $_p: ${problems:-no usable source}"
    n_failed=$((n_failed + 1))
  fi
}

TAB="$(printf '\t')"
records=0

while read -r marker; do
  if [ "$marker" != "FILE" ]; then
    echo "record desync: expected FILE, got '$marker'" >&2; exit 3
  fi
  read -r path
  read -r want
  read -r nsrc
  want="$(echo "$want" | tr '[:upper:]' '[:lower:]')"
  srcs=""
  i=0
  while [ "$i" -lt "$nsrc" ]; do
    read -r auth
    read -r url
    srcs="${srcs}${auth}${TAB}${url}${NL}"
    i=$((i + 1))
  done
  records=$((records + 1))
  flush
done <<OUTER
$(yq -r "$EXPR" "$PACKAGE")
OUTER

# The assertion that makes a silent pass impossible. Reading zero records from a
# package that declares 10 files must never be reported as a clean run -- it is
# how a parser that quietly matched nothing scored "0 failed" and exit 0.
if [ "$records" != "$declared" ]; then
  echo "read $records records but the package declares $declared files" >&2
  exit 3
fi

flush

echo "present:     $n_present"
if [ "$DRY" = 1 ]; then
  echo "would fetch: $n_would"
else
  echo "fetched:     $n_fetched"
  [ "$bytes" = 0 ] || echo "written:     $((bytes / 1000000)) MB"
fi
echo "skipped:     $n_skipped (no source recorded)"
echo "failed:      $n_failed"
if [ "$DRY" = 1 ]; then echo "dry run — re-run with --apply to download"; fi
[ "$n_failed" = 0 ]
