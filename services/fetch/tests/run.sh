#!/bin/sh
# Test suite for the fetch tooling. Runs identically locally and in CI:
#
#   sh services/fetch/tests/run.sh
#
# Cases live here with their fixtures, not inline in a workflow file, so they
# can be run before pushing, linted by shellcheck like everything else, and
# extended without editing CI.
#
# Network is required: these assert against real hosts on purpose. A resolver
# whose tests all mock HTTP would not have caught either of the two bugs that
# prompted this suite -- missing HuggingFace auth, and unencoded spaces in a
# URL -- because both are about what the real service does with a real request.

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
BIN="$(cd "$HERE/.." && pwd)"
FIX="$HERE/fixtures"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

pass=0; fail=0

ok()   { pass=$((pass + 1)); printf '  ok   %s\n' "$1"; }
bad()  { fail=$((fail + 1)); printf '  FAIL %s\n' "$1"; if [ -n "${2:-}" ]; then sed 's/^/         /' "$2"; fi; }

# --- resolve: every bad source is reported, in one pass, with no lock ---------
t_resolve_reports_all() {
  name="resolve reports every bad source and writes no lock"
  if sh "$BIN/resolve.sh" "$FIX/manifest-broken-sources.yaml" > "$WORK/o" 2> "$WORK/e"; then
    bad "$name (succeeded against three broken sources)" "$WORK/e"; return
  fi
  [ -s "$WORK/o" ] && { bad "$name (wrote a partial lock)" "$WORK/o"; return; }
  # shellcheck disable=SC2016  # literal backticks in the expected message.
  for want in 'civitai:2068000' 'does-not-exist-xyz' 'needs `sha256`'; do
    grep -qF "$want" "$WORK/e" || { bad "$name (missing '$want')" "$WORK/e"; return; }
  done
  ok "$name"
}

# --- resolve: a filename with spaces resolves ---------------------------------
# Regression. curl given a raw space produces no output and no error, so the
# file read as absent and the failure named the wrong cause.
t_resolve_encodes_paths() {
  name="resolve percent-encodes a filename containing spaces"
  if sh "$BIN/resolve.sh" "$FIX/manifest-awkward-filename.yaml" > "$WORK/o2" 2> "$WORK/e2"; then
    if grep -q '^  - model:' "$WORK/o2"; then ok "$name"; else bad "$name (no model emitted)" "$WORK/o2"; fi
  else
    bad "$name" "$WORK/e2"
  fi
}

# --- resolve: gated repos need the auth map -----------------------------------
# Skipped rather than failed when no token is configured: the assertion is about
# the code path, and a contributor without HF access should still get a green
# suite rather than a mystery.
t_resolve_authenticates() {
  name="resolve authenticates to HuggingFace for a gated repo"
  if [ -z "${HF_TOKEN:-}" ]; then printf '  skip %s (HF_TOKEN unset)\n' "$name"; return; fi
  cat > "$WORK/gated.yaml" <<YAML
name: gated
auth:
  huggingface.co: \${HF_TOKEN}
models:
  - name: gated
    files:
      - source: hf:black-forest-labs/FLUX.1-Krea-dev
        file: flux1-krea-dev.safetensors
        install: models/unet/
YAML
  if sh "$BIN/resolve.sh" "$WORK/gated.yaml" > "$WORK/o3" 2> "$WORK/e3"; then
    if grep -q 'f6315581b7cddd450b9aba72b4e9ccf8b6580dc1a6b9538aff43ee26a1a3b6c2' "$WORK/o3"; then
      ok "$name"
    else
      bad "$name (resolved, but not to the expected hash)" "$WORK/o3"
    fi
  else
    bad "$name" "$WORK/e3"
  fi
}

# --- check-lock: profiles ------------------------------------------------------
t_check_rejects_unknown_member() {
  name="check-lock rejects a profile naming an unknown capability"
  if sh "$BIN/check-lock.sh" "$FIX/manifest-profile-unknown-member.yaml" "$FIX/lock-good.yaml" > "$WORK/o4" 2>&1; then
    bad "$name" "$WORK/o4"
  else
    if grep -q 'BAD PROFILE' "$WORK/o4"; then ok "$name"; else bad "$name (failed for another reason)" "$WORK/o4"; fi
  fi
}

t_check_rejects_cycle() {
  name="check-lock rejects a profile cycle (a -> b -> a)"
  if sh "$BIN/check-lock.sh" "$FIX/manifest-profile-cycle.yaml" "$FIX/lock-good.yaml" > "$WORK/o5" 2>&1; then
    bad "$name" "$WORK/o5"
  else
    if grep -q 'cycle' "$WORK/o5"; then ok "$name"; else bad "$name (failed for another reason)" "$WORK/o5"; fi
  fi
}

t_check_rejects_unhashed_entry() {
  name="check-lock rejects a lock entry with no SHA256"
  if sh "$BIN/check-lock.sh" "$FIX/manifest-for-lock-good.yaml" "$FIX/lock-no-hash.yaml" > "$WORK/o6" 2>&1; then
    bad "$name" "$WORK/o6"
  else
    if grep -q 'NO SHA256' "$WORK/o6"; then ok "$name"; else bad "$name (failed for another reason)" "$WORK/o6"; fi
  fi
}

t_check_accepts_agreeing_pair() {
  name="check-lock accepts a manifest and lock that agree"
  if sh "$BIN/check-lock.sh" "$FIX/manifest-for-lock-good.yaml" "$FIX/lock-good.yaml" > "$WORK/o7" 2>&1; then
    ok "$name"
  else
    bad "$name" "$WORK/o7"
  fi
}

echo "fetch tooling tests"
t_resolve_reports_all
t_resolve_encodes_paths
t_resolve_authenticates
t_check_rejects_unknown_member
t_check_rejects_cycle
t_check_rejects_unhashed_entry
t_check_accepts_agreeing_pair

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = 0 ]
