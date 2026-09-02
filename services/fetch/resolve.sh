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
# Usage: resolve.sh <comfy.yaml> [--profile <name>] [--from-lock <lock.yaml>]
# Writes a `models:` document to stdout. Redirect it into the lock.
#
# Without --profile every model is resolved. With one, only the capabilities
# that profile names -- expanded transitively, since a profile may name another.
#
# --from-lock SELECTS from an existing lock instead of resolving. Producing N
# profile locks otherwise means N network passes over heavily overlapping files,
# and -- worse -- locks resolved minutes apart can legitimately pin DIFFERENT
# commits if a moving ref advanced between runs. Deriving them all from one
# parent makes every profile pin identical commits by construction, and the
# result is a strict subset of that parent.

set -eu

# Source failures are COLLECTED, not fatal. `set -e` aborting on the first one
# means a manifest of 161 files with a single dead source resolves nothing and
# tells you about one problem per run -- so finding N broken sources costs N
# full passes over the network. Every failure is reported in one pass instead,
# and no lock is written unless all of them resolved: a partial lock that looks
# complete is worse than none.

LC_ALL=C
export LC_ALL

MANIFEST="${1:?usage: resolve.sh <comfy.yaml> [--profile <name>]}"
[ -f "$MANIFEST" ] || { echo "no such manifest: $MANIFEST" >&2; exit 2; }

PROFILE=""
FROM_LOCK=""
shift
while [ "$#" -gt 0 ]; do
  case "$1" in
    --profile)   PROFILE="${2:?--profile needs a name}"; shift 2 ;;
    --from-lock) FROM_LOCK="${2:?--from-lock needs a path}"; shift 2 ;;
    *)           echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [ -n "$FROM_LOCK" ] && [ ! -f "$FROM_LOCK" ]; then
  echo "no such lock: $FROM_LOCK" >&2; exit 2
fi
if [ -n "$FROM_LOCK" ] && [ -z "$PROFILE" ]; then
  echo "--from-lock needs --profile: without one it would copy the lock verbatim" >&2; exit 2
fi

UA="comfyui-fetch/1.0 (+https://github.com/pixeloven/ComfyUI-Docker)"

# shellcheck source=services/fetch/lib-profiles.sh
. "$(dirname "$0")/lib-profiles.sh"
# shellcheck source=services/fetch/lib-auth.sh
. "$(dirname "$0")/lib-auth.sh"

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

# Expand a profile to the capability names it selects. A member may be another
# profile, so this iterates to a fixed point -- and a bounded one, because a
# profile that names itself would otherwise loop forever.
selected=""
if [ -n "$PROFILE" ]; then
  selected=" $(expand_profile "$MANIFEST" "$PROFILE")"
  echo "profile $PROFILE selects:$selected" >&2
fi

in_selection() {
  [ -z "$PROFILE" ] && return 0
  case " $selected " in *" $1 "*) return 0 ;; *) return 1 ;; esac
}

# Unconditionally, and before any request. Placed inside the else branch below
# it would load credentials only when NO --profile was given -- which is the
# path nobody uses, and the failure is silent: gated repos simply report as
# "not found".
auth_load "$MANIFEST"

# --- selection from an existing lock ------------------------------------------
# No network, no resolution: the parent already holds resolved entries, so this
# filters it to the paths the profile selects and copies them VERBATIM.
if [ -n "$FROM_LOCK" ]; then
  selected="$(expand_profile "$MANIFEST" "$PROFILE")" || exit 2
  echo "profile $PROFILE selects (from $FROM_LOCK): $selected" >&2

  want="$(mktemp)"; trap 'rm -f "$want"' EXIT
  for cap in $selected; do
    # Same expression check-lock.sh derives install paths with. `install`
    # already begins `models/`, so nothing needs prefixing -- an earlier version
    # prepended and then sliced, which yq 4.47 rejects outright while 4.53
    # accepts it.
    NAME="$cap" yq -r '.models[] | select(.name == strenv(NAME)) | .files[] |
      .install + (.as // (.file // "" | sub(".*/"; "")))' "$MANIFEST" >> "$want"
  done
  sort -u -o "$want" "$want"

  n_want="$(wc -l < "$want")"
  if [ "$n_want" = 0 ]; then
    echo "profile $PROFILE selects no files" >&2; exit 1
  fi

  # A path the profile wants that the parent does not hold means the parent is
  # stale. Emitting a short lock silently would hide that.
  missing=""
  while read -r path; do
    if [ "$(P="$path" yq -r '[.models[] | select((.paths // [])[0].path == strenv(P))] | length' "$FROM_LOCK")" = "0" ]; then
      missing="${missing}  $path
"
    fi
  done < "$want"
  if [ -n "$missing" ]; then
    echo "" >&2
    echo "these files are selected by $PROFILE but absent from $FROM_LOCK:" >&2
    printf '%s' "$missing" >&2
    echo "The parent lock is stale -- re-resolve it before deriving from it." >&2
    exit 1
  fi

  # Nothing is written until the parent is known to hold every selected path.
  # Emitting the auth block first wrote a partial lock on the stale-parent path
  # -- the same "no partial lock" rule the resolve path already follows.
  if [ "$(yq -r 'has("auth")' "$FROM_LOCK")" = "true" ]; then
    yq -o yaml -r '{"auth": .auth}' "$FROM_LOCK"
  fi

  # One lookup per selected path. Obviously correct beats clever: entries are
  # copied VERBATIM from the parent, so a derived lock is a strict subset of it
  # and every profile pins the same commits.
  echo "models:"
  while read -r path; do
    P="$path" yq -o yaml -r \
      '.models[] | select((.paths // [])[0].path == strenv(P))' "$FROM_LOCK" \
      | sed '1s/^/  - /; 2,$s/^/    /'
  done < "$want"

  exit 0
fi

if [ -n "$PROFILE" ]; then
  declared=0
  for m in $selected; do
    n="$(NAME="$m" yq -r '[.models[] | select(.name == strenv(NAME)) | .files[]] | length' "$MANIFEST")"
    declared=$((declared + n))
  done
else
  auth_load "$MANIFEST"

declared="$(yq -r '[.models[].files[]] | length' "$MANIFEST")"
fi
records=0
failures=0
failed_list=""

fail() {  # <what> ; records the failure and moves on
  echo "  UNRESOLVED  $1" >&2
  failed_list="${failed_list}  $1
"
  failures=$((failures + 1))
}

hf_head() {  # <repo> <revision> <file>  -> commit<TAB>sha256
  # NOT -sIL. `x-linked-etag` is the sha256 only on the FIRST hop; following the
  # redirect returns the CDN's Xet content-address, a different and equally
  # plausible-looking 64-hex value.
  #
  # Authenticated when the manifest maps huggingface.co to a variable that is
  # set. Gated repos -- black-forest-labs publishes as `gated: auto` -- answer
  # 401 without it, which is indistinguishable from a missing file.
  _u="https://huggingface.co/$1/resolve/$2/$(urlencode_path "$3")"
  _t="$(token_for_url "$_u")"
  if [ -n "$_t" ]; then set -- -H "Authorization: Bearer $_t"; else set --; fi
  curl -sI -A "$UA" "$@" "$_u" \
    | tr -d '\r' \
    | awk 'BEGIN{IGNORECASE=1}
           /^x-repo-commit:/ {c=$2}
           /^x-linked-etag:/ {h=$2; gsub(/"/,"",h)}
           END{ if (c && h) printf "%s\t%s", c, h }'
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
  # Skipped BEFORE the record counter and before any network call: an
  # unselected capability must not be resolved, and must not count toward the
  # records assertion either.
  if ! in_selection "$capability"; then continue; fi
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
      if [ -z "$file" ]; then fail "$source: hf source needs \`file\`"; continue; fi
      got="$(hf_head "$repo" "$revision" "$file")"
      if [ -z "$got" ]; then
        _m="$(missing_cred_for_url "https://huggingface.co/")"
        if [ -n "$_m" ]; then
          fail "hf:$repo@$revision/$file: not found, or gated (\$$_m is not set)"
        else
          fail "hf:$repo@$revision/$file: not found, or you lack access to a gated repo"
        fi
        continue
      fi
      commit="$(printf '%s' "$got" | cut -f1)"
      sha="$(printf '%s' "$got" | cut -f2)"
      # The lock pins the COMMIT, never the moving ref it was resolved from.
      # Encoded, so a filename with spaces survives into the lock and the
      # fetcher does not have to re-derive it.
      url="https://huggingface.co/$repo/resolve/$commit/$(urlencode_path "$file")"
      base="$(basename "$file")"
      ;;
    civitai:*)
      id="${source#civitai:}"
      if ! curl -sf -A "$UA" "https://civitai.com/api/v1/model-versions/$id" > "$work/cv.json"; then
        fail "$source: not found (deleted upstream, or the version id is wrong)"; continue
      fi
      url="$(yq -p json -o yaml -r '.files[0].downloadUrl' "$work/cv.json")"
      sha="$(yq -p json -o yaml -r '.files[0].hashes.SHA256 // ""' "$work/cv.json" | tr '[:upper:]' '[:lower:]')"
      base="$(yq -p json -o yaml -r '.files[0].name' "$work/cv.json")"
      # `if`, not `A && B || C` -- the latter runs C when A is true and B is
      # false, which is not if-then-else and would misreport the reason.
      if [ -z "$sha" ] || [ "$sha" = "null" ]; then
        fail "$source: no SHA256 in the API response"; continue
      fi
      ;;
    gh:*)
      # gh:<owner>/<repo>@<tag>. The asset is `file`.
      spec="${source#gh:}"; repo="${spec%@*}"; tag="${spec##*@}"
      if [ -z "$file" ]; then fail "$source: gh source needs \`file\` (the asset name)"; continue; fi
      set --
      if [ -n "${GITHUB_TOKEN:-}" ]; then set -- -H "Authorization: Bearer $GITHUB_TOKEN"; fi
      if ! curl -sf -A "$UA" "$@" "https://api.github.com/repos/$repo/releases/tags/$tag" > "$work/gh.json"; then
        fail "gh:$repo@$tag: release not found"; continue
      fi
      url="$(ASSET="$file" yq -p json -o yaml -r '.assets[] | select(.name == strenv(ASSET)) | .browser_download_url' "$work/gh.json")"
      if [ -z "$url" ] || [ "$url" = "null" ]; then
        fail "gh:$repo@$tag: no asset named $file"; continue
      fi
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
        if ! curl -fsSL -A "$UA" "$url" -o "$work/asset"; then
          fail "gh:$repo@$tag/$file: download failed"; continue
        fi
        sha="$(sha256sum "$work/asset" | cut -d' ' -f1)"
        rm -f "$work/asset"
      fi
      base="$file"
      ;;
    http://*|https://*)
      # Nothing about a bare URL can be resolved from headers, so the manifest
      # must state the hash. Refusing is the honest outcome: writing a lock
      # entry with no hash would produce a fetch that verifies nothing.
      if [ -z "$sha" ]; then fail "$source: a direct URL needs \`sha256\` in the manifest"; continue; fi
      url="$source"
      base="$(basename "${source%%\?*}")"
      ;;
    *) fail "$source: unknown source scheme"; continue ;;
  esac

  if [ -n "$as" ]; then base="$as"; fi
  printf '%s%s\t%s\t%s\t%s\t%s\n' \
    "$install" "$base" "$base" "$url" "$sha" "$type" >> "$work/rows"
  echo "resolved $capability: $base" >&2
done <<EOF
$(yq -r "$EXPR" "$MANIFEST")
END
EOF

# Reading zero records from a manifest that declares files must never be
# reported as success.
if [ "$failures" != 0 ]; then
  echo "" >&2
  echo "$failures of $declared sources did not resolve:" >&2
  printf '%s' "$failed_list" >&2
  echo "" >&2
  echo "No lock written. Fix the manifest and re-run -- every failure above is" >&2
  echo "reported in this one pass, so this should not need repeating." >&2
  exit 1
fi

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
while IFS='	' read -r install base url sha type; do
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
  #
  # Nothing else is written. `models[]` is byte-for-byte comfy-cli's documented
  # shape, so anything that learns to read a comfy-lock reads ours unmodified.
  if [ -n "$type" ]; then printf '    type: %s\n' "$type"; fi
done < "$work/sorted"
