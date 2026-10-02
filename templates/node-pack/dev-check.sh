#!/usr/bin/env bash
# dev-check.sh: restart ComfyUI, wait for it, and report how this node pack
# loaded. From the node-pack template of pixeloven/ComfyUI-Docker
# (templates/node-pack); docs/user-guides/developing-nodes.md there is the guide.
#
# Usage: ./dev-check.sh [--no-restart] [--expect CLASS]... [--workflow FILE] [--timeout SECONDS]
#
#   --no-restart       check the running ComfyUI as it is
#   --expect CLASS     fail unless this pack registers node class CLASS (repeatable)
#   --workflow FILE    also run FILE, a workflow in API format, and report the result
#   --timeout SECONDS  how long to wait for ComfyUI, and for the workflow (default 180)
#
# It calls ComfyUI's own routes, and docker only as the fallback restart:
#   restart  Manager's POST /v2/manager/reboot, which restarts ComfyUI in place;
#            `docker compose restart comfyui` when Manager is off or doesn't answer
#   ready    GET /system_stats
#   load     GET /object_info for the classes whose python_module is
#            custom_nodes.<PACK_NAME>, and GET /internal/logs/raw for the pack's
#            import failures and comfy_entrypoint warnings
#   web      GET /extensions for the pack's JavaScript; each file must return 200
#            and import no path that ComfyUI logs a [DEPRECATION WARNING] for
#   run      POST /prompt with the workflow and nothing else, then GET /history
#
# Settings come from the environment, else from .env beside this script:
# PACK_NAME (required), and COMFY_PORT (8188) or COMFY_URL.
#
# Needs bash (3.2 or later), curl and jq. Exits 0 when every check passes, 1
# when one fails, 2 on a usage error.
set -o pipefail

here="$(cd "$(dirname "$0")" && pwd)"
usage() { sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'; }

no_restart=false
timeout=180
workflow=""
expect=()
while [ $# -gt 0 ]; do
  case "$1" in
    --no-restart) no_restart=true ;;
    --expect|--workflow|--timeout)
      [ $# -ge 2 ] || { echo "$1 needs a value" >&2; exit 2; }
      case "$1" in
        --expect) expect+=("$2") ;;
        --workflow) workflow="$2" ;;
        --timeout) timeout="$2" ;;
      esac
      shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
case "$timeout" in ''|*[!0-9]*) echo "--timeout takes whole seconds" >&2; exit 2 ;; esac
[ -z "$workflow" ] || [ -f "$workflow" ] || { echo "no workflow file $workflow" >&2; exit 2; }
for tool in curl jq; do
  command -v "$tool" >/dev/null || { echo "dev-check.sh needs $tool" >&2; exit 2; }
done

# KEY=value from .env (quotes stripped). The environment wins over it.
dotenv() {
  [ -f "$here/.env" ] || return 0
  sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$here/.env" | tail -n 1 \
    | sed -e "s/[[:space:]]*\$//" -e "s/^[\"']//" -e "s/[\"']\$//"
}
PACK_NAME="${PACK_NAME:-$(dotenv PACK_NAME)}"
[ -n "$PACK_NAME" ] || { echo "PACK_NAME is not set: copy .env.example to .env and set it" >&2; exit 2; }
COMFY_PORT="${COMFY_PORT:-$(dotenv COMFY_PORT)}"
COMFY_URL="${COMFY_URL:-http://127.0.0.1:${COMFY_PORT:-8188}}"
COMFY_URL="${COMFY_URL%/}"
module="custom_nodes.$PACK_NAME"

failures=0
section() { printf '== %s\n' "$*"; }
ok() { printf 'ok    %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; failures=$((failures + 1)); }
note() { printf '      %s\n' "$*"; }
finish() {
  if [ "$failures" = 0 ]; then section "every check passed"; exit 0; fi
  section "$failures check(s) failed"; exit 1
}
answers() { curl -fsS -o /dev/null --max-time 5 "$COMFY_URL/system_stats" 2>/dev/null; }
get() { curl -fsS --max-time 60 "$COMFY_URL$1"; }

restart() {
  local code rc t
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 30 -X POST "$COMFY_URL/v2/manager/reboot" 2>/dev/null)"
  rc=$?
  # Manager re-executes ComfyUI before it can answer, so the connection drops
  # (curl exit 52). Wait until the old process stops answering, so the wait
  # for /system_stats meets the new one.
  if [ "$rc" = 52 ] || { [ "$rc" = 0 ] && [ "$code" = 200 ]; }; then
    t=$SECONDS
    while answers; do
      [ $((SECONDS - t)) -lt 30 ] || { fail "Manager accepted the reboot, but ComfyUI still answers after 30 s"; return 1; }
      sleep 0.2
    done
    ok "restarted in place by Manager (POST /v2/manager/reboot)"
    return 0
  fi
  if [ "$rc" = 0 ]; then
    note "Manager's reboot route answered HTTP $code (is COMFY_ENABLE_MANAGER=true?)"
  else
    note "Manager's reboot route didn't answer (curl exit $rc)"
  fi
  note "restarting the container: docker compose restart comfyui (slower, #120)"
  if ! out="$(cd "$here" && docker compose restart comfyui 2>&1)"; then
    fail "docker compose restart failed: $out"
    return 1
  fi
  ok "restarted the container (docker compose restart comfyui)"
}

section "ComfyUI at $COMFY_URL, pack $PACK_NAME"
if ! $no_restart; then
  restart || finish
fi
start=$SECONDS
until answers; do
  if [ $((SECONDS - start)) -ge "$timeout" ]; then
    fail "no answer from $COMFY_URL/system_stats in $timeout s (docker compose logs comfyui says why)"
    finish
  fi
  sleep 1
done
version="$(get /system_stats | jq -r '.system.comfyui_version // "?"')"
ok "ready after $((SECONDS - start)) s (ComfyUI $version)"

# --- load ----------------------------------------------------------------------
section "load: $module"
info="$(get /object_info)" || { fail "GET /object_info failed"; finish; }
logs="$(get /internal/logs/raw)" || { fail "GET /internal/logs/raw failed"; finish; }

classes="$(jq -r --arg m "$module" '[to_entries[] | select(.value.python_module == $m) | .key] | sort | join(", ")' <<<"$info")"

# Log entries without their colour codes and [LEVEL] prefix.
clean='def clean: gsub("\u001b\\[[0-9;]*m"; "") | sub("^\\[[A-Z]+\\] "; "") | rtrimstr("\n");'
# The log lines that say this pack didn't load, each with the traceback logged
# just before it, if any. ComfyUI names the pack by its path, /app/custom_nodes/<pack>.
problems="$(jq -r --arg p "$PACK_NAME" "$clean"'
  def names_pack: . as $m
    | any(["/", " ", ":", "\n", "\""][] as $end | $m | contains("/custom_nodes/" + $p + $end); .)
      or ($m | endswith("/custom_nodes/" + $p));
  [.entries[].m | clean] as $e
  | range($e | length) as $i
  | $e[$i]
  | select((names_pack and test("IMPORT FAILED|Cannot import|comfy_entrypoint|^Skip |Blocked by policy"))
           or startswith("Skipping " + $p + " due to"))
  | (if $i > 0 and ($e[$i - 1] | startswith("Traceback")) then $e[$i - 1] else empty end), .
' <<<"$logs")"
imported="$(jq -r --arg p "$PACK_NAME" "$clean"'
  .entries[].m | clean | select(contains(" seconds: ") and endswith("/custom_nodes/" + $p))
  | sub("^ +"; "")' <<<"$logs" | tail -n 1)"

if [ -n "$problems" ]; then
  fail "ComfyUI logged that the pack didn't load:"
  printf '%s\n' "$problems" | sed -e '/^$/d' -e 's/^/        /'
elif [ -n "$imported" ]; then
  ok "imported: $imported"
fi
if [ -n "$classes" ]; then
  ok "registers: $classes"
elif [ -z "$problems" ] && [ -z "$imported" ]; then
  fail "no sign of $PACK_NAME: no node classes, and no import line in /internal/logs"
  note "is this repository mounted at /app/custom_nodes/$PACK_NAME, with the same PACK_NAME in .env?"
  note "(the log keeps 300 entries: after a long session, restart without --no-restart)"
else
  note "registers no node classes"
fi

# The V1/V3 trap: with NODE_CLASS_MAPPINGS present, ComfyUI loads the V1
# mappings and never calls comfy_entrypoint, and logs nothing about it.
if [ -f "$here/__init__.py" ] \
  && grep -qw NODE_CLASS_MAPPINGS "$here/__init__.py" && grep -qw comfy_entrypoint "$here/__init__.py"; then
  fail "__init__.py has both NODE_CLASS_MAPPINGS and comfy_entrypoint: ComfyUI loads only NODE_CLASS_MAPPINGS (V1) and ignores comfy_entrypoint (V3), silently. Keep one."
fi

for c in "${expect[@]}"; do
  owner="$(jq -r --arg c "$c" '.[$c].python_module // empty' <<<"$info")"
  if [ "$owner" = "$module" ]; then
    ok "registers $c"
  elif [ -n "$owner" ]; then
    fail "$c is registered by $owner, not this pack: another pack or a built-in node has that class name, and ComfyUI keeps one silently"
  else
    fail "$c is not registered"
  fi
done

# --- web -----------------------------------------------------------------------
section "web: /extensions"
# ComfyUI serves a pack's web directory under its directory name (WEB_DIRECTORY)
# or under its pyproject.toml project name ([tool.comfy] web).
project="$( [ -f "$here/pyproject.toml" ] && sed -n 's/^name[[:space:]]*=[[:space:]]*["'"'"']\([^"'"'"']*\).*/\1/p' "$here/pyproject.toml" | head -n 1)"
if ext="$(get /extensions)"; then
  files="$(jq -r --arg a "/extensions/$PACK_NAME/" --arg b "/extensions/${project:-$PACK_NAME}/" \
    '.[] | select(startswith($a) or startswith($b))' <<<"$ext")"
  if [ -z "$files" ]; then
    note "serves no JavaScript"
  fi
  body="$(mktemp)"
  trap 'rm -f "$body"' EXIT
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    code="$(curl -sS -o "$body" -w '%{http_code}' --max-time 30 "$COMFY_URL$f")"
    if [ "$code" != 200 ]; then
      fail "$f: HTTP $code"
      continue
    fi
    # ComfyUI logs "[DEPRECATION WARNING] Detected import of deprecated legacy
    # API" when a browser fetches /scripts/ui* or /extensions/core/*. The log
    # line names the path, not the extension, so check what the file imports.
    legacy="$(grep -noE '(scripts/ui[./]|extensions/core/)[^"'"'"' )]*' "$body" | head -n 3 | tr '\n' ' ')"
    if [ -n "$legacy" ]; then
      fail "$f imports a deprecated legacy API path: $legacy"
    else
      ok "$f (200)"
    fi
  done <<<"$files"
else
  fail "GET /extensions failed"
fi
deprecations="$(jq -r "$clean"'.entries[].m | clean | select(contains("[DEPRECATION WARNING]"))' <<<"$logs")"
if [ -n "$deprecations" ]; then
  note "ComfyUI logged deprecation warnings (they name the path, not the extension):"
  printf '%s\n' "$deprecations" | sed 's/^/        /'
fi

# --- run -----------------------------------------------------------------------
if [ -n "$workflow" ]; then
  section "run: $workflow"
  # Only the graph is sent: no client id, no extra_data.
  if ! payload="$(jq -c 'if type == "object" and has("prompt") then {prompt: .prompt} else {prompt: .} end' "$workflow")"; then
    fail "$workflow is not JSON"
    finish
  fi
  if jq -e '.prompt | has("nodes") and has("links")' >/dev/null <<<"$payload"; then
    fail "$workflow is in the UI format: export it with Export (API) instead"
    finish
  fi
  reply="$(curl -sS --max-time 60 -w '\n%{http_code}' -H 'Content-Type: application/json' --data-binary "$payload" "$COMFY_URL/prompt")"
  code="${reply##*$'\n'}"
  reply="${reply%$'\n'*}"
  if [ "$code" != 200 ]; then
    fail "ComfyUI rejected the workflow (HTTP $code):"
    jq -c '{error, node_errors}' <<<"$reply" 2>/dev/null | sed 's/^/        /' || note "$reply"
    finish
  fi
  id="$(jq -r .prompt_id <<<"$reply")"
  start=$SECONDS
  while :; do
    entry="$(get "/history/$id" | jq -c --arg id "$id" '.[$id] // empty')"
    status="$(jq -r '.status.status_str // empty' <<<"$entry" 2>/dev/null)"
    [ -n "$status" ] && break
    if [ $((SECONDS - start)) -ge "$timeout" ]; then
      fail "prompt $id did not finish in $timeout s"
      finish
    fi
    sleep 1
  done
  if [ "$status" = success ]; then
    ok "prompt $id completed in $((SECONDS - start)) s; outputs:"
    jq -c '.outputs' <<<"$entry" | sed 's/^/        /'
  else
    fail "prompt $id ended with status $status:"
    jq -c '.status.messages[] | select(.[0] == "execution_error") | .[1] | {node_id, node_type, exception_type, exception_message}' <<<"$entry" | sed 's/^/        /'
  fi
fi

finish
