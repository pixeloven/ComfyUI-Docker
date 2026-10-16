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

# The node venv (#115): the Python packages custom nodes install live in a venv
# on the user volume, layered over the image's. A .pth file puts the image's
# site-packages after the venv's own, so pip sees what the image has and
# installs only what is missing, into the venv, never into /app/.venv. ComfyUI,
# and through it Manager's `python -m pip`, runs from it, so those packages
# survive a recreate. Its bin/ is first on the image's PATH, where its `pip`,
# `pip3` and `cm-cli` do the same for a `docker exec` session.
node_venv=/app/user/__node_venv
manager_config=/app/user/__manager/config.ini
if [ "${COMFY_ENABLE_NODE_VENV:-true}" = "true" ]; then
    py="$(python -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    site="$node_venv/lib/python$py/site-packages"
    if [ ! -d "$site" ]; then
        clear=()
        if [ -e "$node_venv/pyvenv.cfg" ]; then
            # Packages built for another Python can't load: start it over.
            echo "WARNING: $node_venv was made for another Python, so it is recreated empty. Reinstall custom-node dependencies with: cm-cli restore-dependencies --user-directory /app/user/__manager" >&2
            clear=(--clear)
        fi
        python -m venv --without-pip "${clear[@]}" "$node_venv"
        echo "/app/.venv/lib/python$py/site-packages" > "$site/_comfyui_image.pth"
        for tool in pip pip3; do
            printf '#!/bin/sh\nexec %s/bin/python -m pip "$@"\n' "$node_venv" > "$node_venv/bin/$tool"
        done
        # shellcheck disable=SC2016  # expanded by the wrapper when it runs, not here
        printf '#!/bin/sh\nexport COMFYUI_PATH="${COMFYUI_PATH:-/app/ComfyUI}"\nexec %s/bin/python -m cm_cli "$@"\n' \
            "$node_venv" > "$node_venv/bin/cm-cli"
        chmod 0755 "$node_venv/bin/pip" "$node_venv/bin/pip3" "$node_venv/bin/cm-cli"
    fi
    # What the venv's packages were installed against. A pack's compiled
    # dependency can break when the image's torch or numpy moves.
    image="$(python -c 'import importlib.metadata as m, os; print(os.environ.get("COMFYUI_VERSION", ""), *(f"{p}={m.version(p)}" for p in ("torch", "numpy")))')"
    if [ -f "$node_venv/.image" ] && [ "$(cat "$node_venv/.image")" != "$image" ]; then
        echo "NOTICE: the image changed from '$(cat "$node_venv/.image")' to '$image'. If a custom node now fails to import, stop the container, delete $node_venv, start it, and run: cm-cli restore-dependencies --user-directory /app/user/__manager" >&2
    fi
    echo "$image" > "$node_venv/.image" 2>/dev/null || true
    export VIRTUAL_ENV="$node_venv" PATH="$node_venv/bin:$PATH"
fi

# Manager's config.ini. uv can't see the image's packages through the node
# venv's .pth and would reinstall them (torch included) into it, so with the
# venv on, Manager must use pip. COMFY_MANAGER_SECURITY_LEVEL (#125) is opt-in;
# unset, Manager's own security_level stands. Only these keys are written.
# Manager writes its defaults only when the file is missing, and reads a missing
# boolean as false, so a file made here carries the two whose default is true.
manager_settings=()
if [ "${COMFY_ENABLE_NODE_VENV:-true}" = "true" ]; then
    manager_settings+=(use_uv=False use_unified_resolver=False)
fi
if [ -n "${COMFY_MANAGER_SECURITY_LEVEL:-}" ]; then
    case "$COMFY_MANAGER_SECURITY_LEVEL" in
        strong|normal|normal-|weak) manager_settings+=("security_level=$COMFY_MANAGER_SECURITY_LEVEL") ;;
        *)
            echo "ERROR: COMFY_MANAGER_SECURITY_LEVEL must be strong, normal, normal- or weak, not '$COMFY_MANAGER_SECURITY_LEVEL'." >&2
            exit 1
            ;;
    esac
fi
if [ "${#manager_settings[@]}" -gt 0 ]; then
    python - "$manager_config" "${manager_settings[@]}" <<'EOF'
import configparser, os, sys

path, settings = sys.argv[1], dict(arg.split("=", 1) for arg in sys.argv[2:])
config = configparser.ConfigParser(strict=False)
created = not os.path.exists(path)
config.read(path)
if not config.has_section("default"):
    config["default"] = {"use_uv": "True", "file_logging": "True"} if created else {}
section = config["default"]
changed = {key: value for key, value in settings.items() if section.get(key, "").lower() != value.lower()}
if changed:
    for key, value in changed.items():
        if not created:
            print(f"startup: {path}: {key} = {section.get(key, '(unset)')} -> {value}")
        section[key] = value
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        config.write(f)
EOF
fi

exec python "${args[@]}"
