#!/bin/sh
# Profile expansion, shared by resolve.sh and check-lock.sh.
#
# Extracted rather than duplicated: both need to answer "which capabilities does
# this profile select", and two copies of a fixed-point expansion is exactly the
# drift this project keeps arguing against elsewhere.
#
# Sourced, not executed. Defines expand_profile().

# expand_profile <manifest> <profile>  -> space-separated capability names on
# stdout, or a message on stderr and a non-zero return.
#
# A member may be a model name or another profile, so this iterates to a fixed
# point -- and a BOUNDED one, because `a -> b -> a` would otherwise loop
# forever. Checking only for a profile that names itself would miss that.
expand_profile() {
  _m="$1"; _p="$2"
  if [ "$(PROF="$_p" yq -r '.profiles // {} | has(strenv(PROF))' "$_m")" != "true" ]; then
    echo "no such profile: $_p" >&2; return 2
  fi
  _known="$(yq -r '.models[].name' "$_m")"
  _sel=""; _frontier="$_p"; _rounds=0
  while [ -n "$_frontier" ]; do
    _rounds=$((_rounds + 1))
    if [ "$_rounds" -gt 32 ]; then
      echo "profile expansion did not settle after 32 rounds: cycle in profiles?" >&2
      return 2
    fi
    _next=""
    for _member in $_frontier; do
      if printf '%s\n' "$_known" | grep -qx "$_member"; then
        case " $_sel " in *" $_member "*) ;; *) _sel="$_sel $_member" ;; esac
      elif [ "$(PROF="$_member" yq -r '.profiles // {} | has(strenv(PROF))' "$_m")" = "true" ]; then
        _next="$_next $(PROF="$_member" yq -r '.profiles[strenv(PROF)][]' "$_m" | tr '\n' ' ')"
      else
        echo "profile member is neither a model nor a profile: $_member" >&2
        return 2
      fi
    done
    _frontier="$_next"
  done
  printf '%s' "${_sel# }"
}
