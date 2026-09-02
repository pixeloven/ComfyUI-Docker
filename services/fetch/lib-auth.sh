#!/bin/sh
# Host-keyed credential lookup, shared by resolve.sh and fetch-lock.sh.
#
# Extracted rather than duplicated: both need to answer "which token, if any,
# does this URL's host want", and the manifest and the lock carry the same
# `auth` map. Two copies would drift.
#
# Sourced, not executed. Call auth_load <file> once, then token_for_url <url>.

# The map's values are ${ENV_VAR} references, never literals -- the schema
# rejects a literal so a token cannot be committed.
auth_load() { _auth_map="$(yq -r '.auth // {} | to_entries[] | .key + " " + .value' "$1" 2>/dev/null || true)"; }

host_of() { _h="${1#*://}"; _h="${_h%%/*}"; printf '%s' "${_h%%:*}"; }

# The env var mapped to a host, or empty.
var_for_host() {
  printf '%s\n' "${_auth_map:-}" | while read -r _host _ref; do
    if [ "$_host" = "$1" ]; then
      _ref="${_ref#\$\{}"; printf '%s' "${_ref%\}}"; return
    fi
  done
}

token_for_url() {
  _v="$(var_for_host "$(host_of "$1")")"
  [ -n "$_v" ] || return 0
  eval "printf '%s' \"\${$_v:-}\""
}

# Named only to make a failure message accurate: a host with a declared
# credential whose variable is unset is the likeliest cause of a 401.
missing_cred_for_url() {
  _v="$(var_for_host "$(host_of "$1")")"
  [ -n "$_v" ] || return 0
  eval "_t=\"\${$_v:-}\""
  [ -n "$_t" ] || printf '%s' "$_v"
}

# Percent-encode a URL PATH, leaving `/` intact.
#
# HuggingFace filenames routinely contain spaces and parentheses -- "Anime v1.3
# (1).safetensors" is a real one. curl given a raw space produces NO output and
# no error, so the file reads as absent rather than as a malformed request.
urlencode_path() {
  printf '%s' "$1" | awk '
    BEGIN { for (i = 0; i < 256; i++) ord[sprintf("%c", i)] = i }
    {
      out = ""
      n = split($0, ch, "")
      for (i = 1; i <= n; i++) {
        c = ch[i]
        if (c ~ /[A-Za-z0-9._~\/-]/) out = out c
        else out = out sprintf("%%%02X", ord[c])
      }
      printf "%s", out
    }'
}
