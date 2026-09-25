#!/bin/bash
# A fixed system PATH for the setup steps below. Both paths activate the venv
# just before starting ComfyUI, which puts /app/.venv/bin first again.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
set -e

# =============================================================================
# Root Detection
# =============================================================================

# When running as non-root (K8s securityContext.runAsUser), activate the
# venv and exec directly — no privilege management needed.
if [ "$(id -u)" -ne 0 ]; then
    echo "Starting as non-root UID:GID = $(id -u):$(id -g)"

    # Inject /etc/passwd and /etc/group entries for the current UID/GID
    # if they don't already exist. Many tools depend on these lookups:
    #   - Python: getpass.getuser(), os.path.expanduser("~"), grp.getgrgid()
    #   - PyTorch: cache_dir resolution via getpwuid()
    # This is standard practice for arbitrary UID containers (OpenShift, etc.)
    if ! getent passwd "$(id -u)" &>/dev/null; then
        echo "comfyuser:x:$(id -u):$(id -g):ComfyUI User:/app:/bin/bash" >> /etc/passwd
    fi
    if ! getent group "$(id -g)" &>/dev/null; then
        echo "comfygroup:x:$(id -g):" >> /etc/group
    fi

    source /app/.venv/bin/activate
    exec "$@"
fi

# =============================================================================
# Root-mode: Dynamic User Setup (Docker/Compose PUID/PGID support)
# =============================================================================
# Default path when running as root (Docker/Compose). Set PUID/PGID
# env vars to control the runtime user identity.

# Default UID/GID values for backward compatibility
PUID=${PUID:-1000}
PGID=${PGID:-1000}
USERNAME="comfy"

# =============================================================================
# Input Validation
# =============================================================================

validate_id() {
    local name="$1"
    local value="$2"

    # Check if numeric
    if ! [[ "$value" =~ ^[0-9]+$ ]]; then
        echo "ERROR: Invalid $name value '$value'. Must be a positive integer." >&2
        exit 1
    fi

    # Check range (0-65534 for broad compatibility)
    if [ "$value" -gt 65534 ]; then
        echo "ERROR: Invalid $name value '$value'. Must be between 0 and 65534." >&2
        exit 1
    fi
}

validate_id "PUID" "$PUID"
validate_id "PGID" "$PGID"

# Warn if running as root
if [ "$PUID" -eq 0 ]; then
    echo "WARNING: Running as root (PUID=0). This is not recommended." >&2
fi

# =============================================================================
# User/Group Creation
# =============================================================================

# Create group if GID doesn't exist. The image already has a "comfy" group
# (GID 1000), so a new entry gets a name unique to its ID.
if ! getent group "$PGID" > /dev/null 2>&1; then
    groupadd -g "$PGID" "$USERNAME-$PGID"
fi
GROUP_NAME=$(getent group "$PGID" | cut -d: -f1)

# Create user if UID doesn't exist, likewise named for its ID
if ! getent passwd "$PUID" > /dev/null 2>&1; then
    useradd -u "$PUID" -g "$PGID" -d /app -s /bin/bash -M "$USERNAME-$PUID"
fi

# User setup is done; give the account files their normal mode. Non-fatal:
# if they are mounted read-only, they cannot be written anyway.
chmod 644 /etc/passwd /etc/group 2>/dev/null || true
if [ -n "$(find /etc/passwd /etc/group -perm -o+w)" ]; then
    echo "WARNING: could not tighten account file permissions." >&2
fi

# =============================================================================
# Directory Ownership
# =============================================================================

# Set ownership of application and persistent volume roots. Keep this
# non-recursive: model stores can contain terabytes of data. -h changes a
# symlink itself, never its target, and a symlinked volume root is skipped.
chown -h "$PUID:$PGID" /app /app/ComfyUI
for directory in \
    /app/models \
    /app/custom_nodes \
    /app/datasets \
    /app/input \
    /app/output \
    /app/temp \
    /app/user; do
    if [ -d "$directory" ] && [ ! -L "$directory" ]; then
        chown -h "$PUID:$PGID" "$directory"
    fi
done

# =============================================================================
# Startup Logging
# =============================================================================

echo "Starting with UID:GID = $PUID:$PGID"

# =============================================================================
# Privilege Drop and Execution
# =============================================================================

# Activate venv and exec as target user
# Using exec ensures no root shell remains in process tree
exec gosu "$PUID:$PGID" bash -c '
    source /app/.venv/bin/activate
    exec "$@"
' -- "$@"
