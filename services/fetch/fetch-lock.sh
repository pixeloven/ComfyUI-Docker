#!/bin/sh
# Materialise the models a comfy-lock.yaml declares, verifying every one.
#
# The lock records WHERE to get each file and WHAT SHOULD ARRIVE. This checks
# the second before committing the first.
#
#   A fetch is verified, not trusted. A wrong-but-plausible model file is worse
#   than a missing one -- a missing file fails loudly at load, a wrong one
#   renders subtly wrong images forever with no error anywhere.
#
#   A partial file is never left in place. Downloads land on a temporary sibling
#   and are renamed only after the hash matches, so an interrupted run leaves
#   the workspace exactly as it found it.
#
# Dependencies: curl, sha256sum, yq. No language runtime.
#
# Usage: fetch-lock.sh <comfy-lock.yaml> <comfyui-root> [--apply]
#
# Paths in the lock are relative to the ComfyUI ROOT (they begin `models/`), so
# the second argument is the workspace root, not the models directory.
# Dry run unless --apply. Exit 0 if nothing failed.

set -eu

LOCK="${1:?usage: fetch-lock.sh <comfy-lock.yaml> <comfyui-root> [--apply]}"
ROOT="${2:?usage: fetch-lock.sh <comfy-lock.yaml> <comfyui-root> [--apply]}"
APPLY="${3:-}"

[ -f "$LOCK" ] || { echo "no such lock: $LOCK" >&2; exit 2; }

case "$APPLY" in
  --apply) DRY=0 ;;
  "")      DRY=1 ;;
  *)       echo "unknown argument: $APPLY" >&2; exit 2 ;;
esac

# Counters, reported explicitly rather than inferred. A run that reported
# "0 fetched, N already present" against an EMPTY directory is the exact failure
# this accounting exists to make impossible: "not downloaded" is never allowed
# to read as "already correct".
n_present=0; n_fetched=0; n_skipped=0; n_failed=0; n_would=0; bytes=0

# Field-per-line, no escapes anywhere: yq 4.47 emits "\t" inside an expression
# literally where 4.53 interprets it, and a delimiter-based parser therefore
# matches nothing, processes zero files and exits 0 against one of them.
#
# Absent values are emitted as "-", never as an empty line: $(...) strips
# TRAILING newlines, so a record ending in an empty field loses it and `read`
# then desynchronises or hits EOF.
EXPR='.models[] |
  ["F", .model, .url,
   ([(.hashes // [])[] | select(.type == "SHA256") | .hash][0] // "-"),
   ((.paths // []) | length | tostring)]
  + [(.paths // [])[].path] | .[]'

declared="$(yq -r '.models | length' "$LOCK")"
records=0

# Credentials are resolved by the URL's HOST, from the lock's top-level `auth`
# map, so no model entry carries an auth field and `models[]` stays exactly
# comfy-cli's documented shape.
#
# The map's values are ${ENV_VAR} references, never literals -- the schema
# rejects a literal so a token cannot be committed.
auth_map="$(yq -r '.auth // {} | to_entries[] | .key + " " + .value' "$LOCK" 2>/dev/null || true)"

host_of() { h="${1#*://}"; h="${h%%/*}"; printf '%s' "${h%%:*}"; }

# The env var mapped to a host, or empty.
var_for_host() {
  printf '%s\n' "$auth_map" | while read -r host ref; do
    if [ "$host" = "$1" ]; then
      ref="${ref#\$\{}"; printf '%s' "${ref%\}}"; return
    fi
  done
}

token_for_url() {
  v="$(var_for_host "$(host_of "$1")")"
  [ -n "$v" ] || return 0
  eval "printf '%s' \"\${$v:-}\""
}

# Named only to make a failure message accurate: a host with a declared
# credential whose variable is unset is the likeliest cause of a 401 or of an
# HTML error page failing the hash check.
missing_cred_for_url() {
  v="$(var_for_host "$(host_of "$1")")"
  [ -n "$v" ] || return 0
  eval "t=\"\${$v:-}\""
  [ -n "$t" ] || printf '%s' "$v"
}

hash_of() { sha256sum "$1" | cut -d' ' -f1; }

while read -r marker; do
  [ "$marker" = "F" ] || { echo "record desync at '$marker'" >&2; exit 3; }
  read -r model; read -r url; read -r want; read -r npaths
  records=$((records + 1))
  [ "$want" = "-" ] && want=""
  want="$(echo "$want" | tr '[:upper:]' '[:lower:]')"

  # Every path this model installs to. The first is fetched; the rest are
  # copies, because ComfyUI resolves some models through more than one
  # search path and the lock is allowed to say so.
  paths=""
  i=0
  while [ "$i" -lt "$npaths" ]; do
    read -r p
    paths="${paths}${p}
"
    i=$((i + 1))
  done

  target="$ROOT/$(echo "$paths" | head -1)"

  if [ -f "$target" ] && [ -n "$want" ] && [ "$(hash_of "$target")" = "$want" ]; then
    n_present=$((n_present + 1))
  elif [ -z "$url" ] || [ "$url" = "null" ]; then
    echo "  SKIP    $model: no url recorded"
    n_skipped=$((n_skipped + 1))
  elif [ -z "$want" ]; then
    # A lock entry with no SHA256 cannot be verified, and fetching it would
    # put unverified bytes in the workspace under the guise of a verified run.
    echo "  SKIP    $model: no SHA256 in the lock, refusing to fetch unverified"
    n_skipped=$((n_skipped + 1))
  elif [ "$DRY" = 1 ]; then
    n_would=$((n_would + 1))
  else
    tok="$(token_for_url "$url")"
    # A host with a declared credential whose variable is unset is NOT blocked:
    # most HuggingFace files are public, and refusing them because HF_TOKEN
    # happens to be unset would be wrong. It is recorded instead, and named in
    # the failure message if the fetch then fails -- which is the case a bare
    # "sha256 mismatch" would otherwise misattribute, since an unauthenticated
    # Civitai request returns an HTML error page with HTTP 200.
    miss="$(missing_cred_for_url "$url")"
    if [ -n "$miss" ]; then hint=" (\$$miss is not set)"; else hint=""; fi
    if true; then
      tmp="$target.fetch-tmp"
      # A destination that cannot be written is not a transfer problem. Checked
      # before the request so the error names the real cause.
      if ! mkdir -p "$(dirname "$target")" 2>/dev/null || ! : > "$tmp" 2>/dev/null; then
        echo "  FAILED  $model: destination not writable"
        n_failed=$((n_failed + 1))
      else
        if [ -n "$tok" ]; then set -- -H "Authorization: Bearer $tok"; else set --; fi
        if ! curl -fsSL --retry 3 --retry-delay 2 --connect-timeout 30 "$@" -o "$tmp" "$url"; then
          rm -f "$tmp"
          echo "  FAILED  $model: transfer failed$hint"
          n_failed=$((n_failed + 1))
        elif [ "$(hash_of "$tmp")" != "$want" ]; then
          rm -f "$tmp"
          echo "  FAILED  $model: sha256 mismatch$hint"
          n_failed=$((n_failed + 1))
        else
          sz=$(wc -c < "$tmp")
          mv "$tmp" "$target"
          bytes=$((bytes + sz)); n_fetched=$((n_fetched + 1))
          # Additional install paths get a copy of the verified bytes.
          echo "$paths" | tail -n +2 | while read -r extra; do
            [ -n "$extra" ] || continue
            mkdir -p "$(dirname "$ROOT/$extra")"
            cp "$target" "$ROOT/$extra"
          done
        fi
      fi
    fi
  fi
done <<EOF
$(yq -r "$EXPR" "$LOCK")
EOF

# Reading zero records from a lock that declares models must never be reported
# as a clean run.
if [ "$records" != "$declared" ]; then
  echo "read $records records but the lock declares $declared models" >&2
  exit 3
fi

echo "present:     $n_present"
if [ "$DRY" = 1 ]; then
  echo "would fetch: $n_would"
else
  echo "fetched:     $n_fetched"
  if [ "$bytes" != 0 ]; then echo "written:     $((bytes / 1000000)) MB"; fi
fi
echo "skipped:     $n_skipped"
echo "failed:      $n_failed"
if [ "$DRY" = 1 ]; then echo "dry run — re-run with --apply to download"; fi
[ "$n_failed" = 0 ]
