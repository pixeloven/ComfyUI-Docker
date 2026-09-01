#!/bin/sh
# Is comfy-lock.yaml consistent with comfy.yaml?
#
# Manifest declares intent; lock records resolution. This checks they still
# describe the same set of files, OFFLINE.
#
# Deliberately NOT "re-resolve and diff". A moving `revision:` is SUPPOSED to
# resolve to a new commit and a new hash once upstream moves, so a re-resolve
# gate would fail for the one reason that is not a mistake -- and would need
# network access in CI to do it. Hash changes come from a deliberate
# `resolve.sh` run, reviewed like any other diff.
#
# Usage: check-lock.sh <comfy.yaml> <comfy-lock.yaml>
# Exit 1 on a file declared but not locked, locked but not declared, or a lock
# entry with no SHA256.

set -eu

LC_ALL=C
export LC_ALL

MANIFEST="${1:?usage: check-lock.sh <comfy.yaml> <comfy-lock.yaml>}"
LOCK="${2:?usage: check-lock.sh <comfy.yaml> <comfy-lock.yaml>}"
[ -f "$MANIFEST" ] || { echo "no such manifest: $MANIFEST" >&2; exit 2; }
[ -f "$LOCK" ]     || { echo "no such lock: $LOCK" >&2; exit 2; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Profiles are validated here rather than at resolve time: a typo in a profile
# member is only discovered when someone resolves THAT profile, which may be
# never. This is offline and costs nothing.
prof_bad=0
known="$(yq -r '.models[].name' "$MANIFEST")"
profiles="$(yq -r '.profiles // {} | keys | .[]' "$MANIFEST")"
for prof in $profiles; do
  for member in $(PROF="$prof" yq -r '.profiles[strenv(PROF)][]' "$MANIFEST"); do
    if printf '%s\n' "$known" | grep -qx "$member"; then continue; fi
    if printf '%s\n' "$profiles" | grep -qx "$member"; then continue; fi
    echo "  BAD PROFILE $prof -> $member is neither a model nor a profile"
    prof_bad=1
  done
done

# Cycle detection, by bounded expansion. Checking only for a profile that names
# ITSELF would miss `a -> b -> a`, which is the same defect one step further
# out -- and the resolver would then be the only thing that caught it, at run
# time, on whoever happened to select that profile.
for prof in $profiles; do
  frontier="$prof"; rounds=0
  while [ -n "$frontier" ]; do
    rounds=$((rounds + 1))
    if [ "$rounds" -gt 32 ]; then
      echo "  BAD PROFILE $prof does not settle: cycle"
      prof_bad=1
      break
    fi
    next=""
    for member in $frontier; do
      if printf '%s\n' "$profiles" | grep -qx "$member"; then
        next="$next $(PROF="$member" yq -r '.profiles[strenv(PROF)][]' "$MANIFEST" | tr '\n' ' ')"
      fi
    done
    frontier="$next"
  done
done

# Expected install paths, derived from the manifest alone. `as` wins; otherwise
# the basename of `file`. The schema requires `as` for civitai sources, whose
# filename is only knowable from the API.
# shellcheck disable=SC2016  # $m is a yq variable.
yq -r '.models[] as $m | $m.files[] |
  .install + (.as // (.file // "" | sub(".*/"; "")))' "$MANIFEST" | sort -u > "$work/declared"

yq -r '.models[] | (.paths // [])[].path' "$LOCK" | sort -u > "$work/locked"

# A lock entry with no SHA256 is unverifiable, and fetch-lock.sh refuses it --
# so it must not pass this gate either.
yq -r '.models[] | select([(.hashes // [])[] | select(.type == "SHA256")] | length == 0) | .model' \
  "$LOCK" | grep -v '^$' > "$work/unhashed" || true

# Two empty files compare equal. Without this, a broken expression or an empty
# manifest reports the gate as PASSING.
for f in "$work/declared" "$work/locked"; do
  if [ ! -s "$f" ]; then
    echo "GATE BROKEN: $(basename "$f") is empty; the comparison would be vacuous" >&2
    exit 1
  fi
done

missing="$(comm -23 "$work/declared" "$work/locked")"
extra="$(comm -13 "$work/declared" "$work/locked")"
unhashed="$(cat "$work/unhashed")"

echo "declared: $(wc -l < "$work/declared")"
echo "locked:   $(wc -l < "$work/locked")"

rc=0
if [ -n "$missing" ]; then
  echo "$missing" | sed 's/^/  NOT LOCKED  /'
  echo "  -> declared in the manifest but absent from the lock; run resolve.sh"
  rc=1
fi
if [ -n "$extra" ]; then
  echo "$extra" | sed 's/^/  NOT DECLARED /'
  echo "  -> in the lock but not the manifest; the lock is generated, so remove it there"
  rc=1
fi
if [ -n "$unhashed" ]; then
  echo "$unhashed" | sed 's/^/  NO SHA256   /'
  echo "  -> unverifiable; fetch-lock.sh will refuse these"
  rc=1
fi
if [ "$prof_bad" != 0 ]; then rc=1; fi
[ "$rc" = 0 ] && echo "manifest and lock agree; $(printf '%s\n' "$profiles" | grep -c .) profiles valid"
exit "$rc"
