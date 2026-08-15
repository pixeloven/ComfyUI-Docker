#!/bin/bash
set -e

args=(
    main.py
    --listen
    --port "${COMFY_PORT:-8188}"
    --base-directory /app
    --database-url sqlite:////app/user/comfyui.db
)

if [ "${COMFY_RUNTIME:-cuda}" = "cpu" ]; then
    args+=(--cpu)
fi

# Manager is an upstream package and is enabled by default in these images.
if [ "${COMFY_ENABLE_MANAGER:-true}" = "true" ]; then
    args+=(--enable-manager)
fi

# The assets API and index back the current Assets sidebar. Hashing remains an
# explicit opt-in because it can make startup expensive on large model stores.
if [ "${COMFY_ENABLE_ASSETS:-true}" = "true" ]; then
    args+=(--enable-assets)
fi

if [ -f /app/extra_model_paths.yaml ]; then
    args+=(--extra-model-paths-config /app/extra_model_paths.yaml)
fi

# CLI_ARGS is intentionally a whitespace-delimited escape hatch. Prefer the
# dedicated environment variables above for built-in container behavior.
if [ -n "${CLI_ARGS:-}" ]; then
    read -r -a extra_args <<< "$CLI_ARGS"
    args+=("${extra_args[@]}")
fi

exec python "${args[@]}"
