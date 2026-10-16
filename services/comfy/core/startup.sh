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

# COMFY_MANAGER_SECURITY_LEVEL (#125) is opt-in. A value Manager doesn't know
# is the one thing in this file that stops the container.
if [ -n "${COMFY_MANAGER_SECURITY_LEVEL:-}" ]; then
    case "$COMFY_MANAGER_SECURITY_LEVEL" in
        strong|normal|normal-|weak) ;;
        *)
            echo "ERROR: COMFY_MANAGER_SECURITY_LEVEL must be strong, normal, normal- or weak, not '$COMFY_MANAGER_SECURITY_LEVEL'." >&2
            exit 1
            ;;
    esac
fi

warn() { echo "WARNING: $*" >&2; }

# Write file $1 with content $2 and mode $3, only when it differs, through a
# temporary file, so an interrupted start never leaves half of one.
put() {
    if [ -f "$1" ] && [ "$(cat "$1")" = "$2" ]; then
        return 0
    fi
    printf '%s\n' "$2" > "$1.tmp" && chmod "$3" "$1.tmp" && mv -f "$1.tmp" "$1"
}

# The node venv (#115): the Python packages custom nodes install live in a venv
# on the user volume, layered over the image's. A .pth file puts the image's
# site-packages after the venv's own, so pip sees what the image has and
# installs only what is missing, into the venv, never into /app/.venv. ComfyUI,
# and through it Manager's `python -m pip`, runs from it, so those packages
# survive a recreate. Its bin/ is first on the image's PATH, where its `pip`,
# `pip3` and `cm-cli` do the same for a `docker exec` session, and its `uv`
# refuses `uv pip`, which can't see the image's packages.
#
# Every start checks and repairs it, and nothing here stops ComfyUI from
# starting: if the venv can't be made usable, ComfyUI runs from the image's
# venv, as in 6.0.0, with a WARNING.
node_venv=/app/user/__node_venv
node_venv_used=false
if [ "${COMFY_ENABLE_NODE_VENV:-true}" = "true" ]; then
    py="$(python -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    image_site="/app/.venv/lib/python$py/site-packages"
    site="$node_venv/lib/python$py/site-packages"
    made_for="$(sed -n 's/^version *= *\([0-9]*\.[0-9]*\).*/\1/p' "$node_venv/pyvenv.cfg" 2>/dev/null || true)"
    clear=()
    if [ -n "$made_for" ] && [ "$made_for" != "$py" ]; then
        # Packages built for another Python can't load: start it over.
        warn "$node_venv was made for Python $made_for, not $py, so it is recreated empty. Reinstall custom-node dependencies with: cm-cli restore-dependencies --user-directory /app/user/__manager"
        clear=(--clear)
    fi
    # Missing, or left half-made by an interrupted start: (re)make it. Without
    # --clear this keeps the packages already in it.
    if [ "${#clear[@]}" -gt 0 ] || [ ! -x "$node_venv/bin/python" ] || [ ! -d "$site" ]; then
        python -m venv --without-pip "${clear[@]}" "$node_venv" || warn "could not make $node_venv"
    fi
    if [ -d "$site" ]; then
        put "$site/_comfyui_image.pth" "$image_site" 0644 || warn "could not write $site/_comfyui_image.pth"
        for tool in pip pip3; do
            put "$node_venv/bin/$tool" "$(printf '#!/bin/sh\nexec %s/bin/python -m pip "$@"' "$node_venv")" 0755 \
                || warn "could not write $node_venv/bin/$tool"
        done
        # shellcheck disable=SC2016  # expanded by the wrapper when it runs, not here
        put "$node_venv/bin/cm-cli" "$(printf '#!/bin/sh\nexport COMFYUI_PATH="${COMFYUI_PATH:-/app/ComfyUI}"\nexec %s/bin/python -m cm_cli "$@"' "$node_venv")" 0755 \
            || warn "could not write $node_venv/bin/cm-cli"
        # shellcheck disable=SC2016  # expanded by the wrapper when it runs, not here
        put "$node_venv/bin/uv" "$(printf '#!/bin/sh\nif [ "$1" = pip ]; then\n    echo "uv pip cannot see the image'"'"'s packages through %s and would reinstall them into it. Use pip (or python -m pip) instead." >&2\n    exit 2\nfi\nexec /app/.venv/bin/uv "$@"' "$node_venv")" 0755 \
            || warn "could not write $node_venv/bin/uv"
    fi
    # Usable means its python runs and sees the image's packages. Then: warn
    # about any image package it shadows, and note when the image changed
    # under it, since a pack's compiled dependency can break when torch or
    # numpy moves.
    if "$node_venv/bin/python" - "$node_venv" "$site" "$image_site" <<'EOF'
import importlib.metadata as md, os, re, sys

venv, site, image_site = sys.argv[1:4]
if image_site not in sys.path:
    sys.exit(1)
try:
    def dists(path):
        found = {}
        for d in md.distributions(path=[path]):
            name = d.metadata["Name"]
            if name:
                found[re.sub(r"[-_.]+", "-", name).lower()] = d.version
        return found

    mine, image = dists(site), dists(image_site)
    shadowed = sorted(set(mine) & set(image))
    if shadowed:
        listed = ", ".join(f"{n} {mine[n]} (image: {image[n]})" for n in shadowed)
        print(f"WARNING: {venv} has its own copy of {len(shadowed)} package(s) the image ships, and its copy wins: {listed}", file=sys.stderr)
        core = [n for n in shadowed if n in ("torch", "torchvision", "torchaudio", "numpy") or n.startswith("comfyui")]
        if core:
            print(f"WARNING: that includes {' '.join(core)}, which ComfyUI itself uses. To go back to the image's, run `pip uninstall -y {' '.join(core)}` in a docker exec session as the runtime user (it removes only the node venv's copies), then restart.", file=sys.stderr)
    stamp = " ".join([os.environ.get("COMFYUI_VERSION", "")] + [f"{p}={image[p]}" for p in ("torch", "numpy") if p in image])
    marker = os.path.join(venv, ".image")
    try:
        with open(marker) as f:
            old = f.read().strip()
    except OSError:
        old = None
    if old is not None and old != stamp:
        print(f"NOTICE: the image changed from '{old}' to '{stamp}'. If a custom node now fails to import, stop the container, delete {venv}, start it, and run: cm-cli restore-dependencies --user-directory /app/user/__manager", file=sys.stderr)
    if old != stamp:
        try:
            with open(marker, "w") as f:
                f.write(stamp + "\n")
        except OSError:
            pass
except Exception as e:
    print(f"WARNING: could not check {venv}: {type(e).__name__}: {e}", file=sys.stderr)
EOF
    then
        export VIRTUAL_ENV="$node_venv" PATH="$node_venv/bin:$PATH"
        node_venv_used=true
    else
        warn "$node_venv can't be used, so ComfyUI runs from the image's venv this time, and what custom nodes install there is lost on a recreate. Make it writable by $(id -u):$(id -g), or delete it, and restart."
    fi
fi

# Manager's config.ini. uv can't see the image's packages through the node
# venv's .pth and would reinstall them (torch included) into it, so while
# ComfyUI runs from the node venv, Manager must use pip. With
# COMFY_MANAGER_SECURITY_LEVEL set, it is written too. Only these keys are
# written, only when they differ, and a failure is a WARNING, never fatal.
# Manager writes its defaults only when the file is missing, and reads a missing
# boolean as false, so a file made here carries the two whose default is true.
manager_settings=()
if [ "$node_venv_used" = true ]; then
    manager_settings+=(use_uv=False use_unified_resolver=False)
fi
if [ -n "${COMFY_MANAGER_SECURITY_LEVEL:-}" ]; then
    manager_settings+=("security_level=$COMFY_MANAGER_SECURITY_LEVEL")
fi
if [ "${#manager_settings[@]}" -gt 0 ]; then
    python - /app/user/__manager/config.ini "${manager_settings[@]}" <<'EOF' || warn "could not update Manager's config.ini"
import configparser, os, sys

path, settings = sys.argv[1], dict(arg.split("=", 1) for arg in sys.argv[2:])
try:
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
        with open(path + ".tmp", "w") as f:
            config.write(f)
        os.replace(path + ".tmp", path)
except Exception as e:
    wanted = ", ".join(f"{k} = {v}" for k, v in settings.items())
    print(f"WARNING: could not set {wanted} in {path} ({type(e).__name__}: {e}). Manager uses the file as it is.", file=sys.stderr)
EOF
fi

exec python "${args[@]}"
