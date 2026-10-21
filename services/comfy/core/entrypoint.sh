#!/bin/bash
# A fixed system PATH for the setup steps below. Both paths activate the venv
# just before starting ComfyUI, which puts /app/.venv/bin first again.
export PATH=/usr/local/nvidia/bin:/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
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
        echo "ERROR: Invalid $name value '$value'. Must be a non-negative integer." >&2
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
# Plain decimal from here on, so 01001 compares equal to the 1001 that stat,
# getent and id print.
PUID=$((10#$PUID))
PGID=$((10#$PGID))

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

# Keep the supplementary groups this process was started with (#122), such as
# Docker's group_add for /dev/dri and /dev/kfd. gosu sets only the groups
# /etc/group lists for the user, and only when given the UID alone, which takes
# the primary group from the passwd entry. So the user joins each one (a GID
# with no name gets one), and gosu gets the UID alone if that entry's group is
# PGID. Otherwise, as for an existing user with another group, the entry is
# left alone (usermod -g also regroups files under its home, /app) and ComfyUI
# runs without them, with a warning.
gosu_user="$PUID:$PGID"
keep_groups() {
    local user gid group
    user="$(getent passwd "$PUID" | cut -d: -f1)" || return 1
    [ "$(getent passwd "$PUID" | cut -d: -f4)" = "$PGID" ] || return 1
    for gid in "${extra_gids[@]}"; do
        if ! getent group "$gid" > /dev/null 2>&1; then
            groupadd -g "$gid" "$USERNAME-$gid" || return 1
        fi
        group="$(getent group "$gid" | cut -d: -f1)" || return 1
        usermod -aG "$group" "$user" || return 1
    done
}
extra_gids=()
for gid in $(id -G); do
    if [ "$gid" -ne 0 ] && [ "$gid" -ne "$PGID" ]; then
        extra_gids+=("$gid")
    fi
done
if [ "${#extra_gids[@]}" -gt 0 ]; then
    if keep_groups; then
        # The UID-alone form grants every group /etc/group lists for this user
        # name, not only the ones started with (the image lists none today).
        gosu_user="$PUID"
    else
        echo "WARNING: could not keep the supplementary groups ${extra_gids[*]} for $PUID:$PGID, so ComfyUI runs without them. Starting the container as $PUID:$PGID (Compose user:) keeps them, but a non-root start changes no owner, so the volumes must already be writable by $PUID:$PGID." >&2
    fi
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
# Only an owner that differs is changed (#114), and a chown that fails, on a
# read-only mount or a root-squashed NFS export, warns instead of exiting (#113).
own() {
    if [ "$(stat -c %u:%g "$1")" != "$PUID:$PGID" ]; then
        chown -h "$PUID:$PGID" "$1" \
            || echo "WARNING: could not change the owner of $1 to $PUID:$PGID (read-only, or root-squashed NFS?); it stays $(stat -c %u:%g "$1")." >&2
    fi
}
own /app
if [ -d /app/ComfyUI ] && [ ! -L /app/ComfyUI ]; then
    own /app/ComfyUI
fi
for directory in \
    /app/models \
    /app/custom_nodes \
    /app/datasets \
    /app/input \
    /app/output \
    /app/temp \
    /app/user; do
    if [ -d "$directory" ] && [ ! -L "$directory" ]; then
        own "$directory"
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
exec gosu "$gosu_user" bash -c '
    source /app/.venv/bin/activate
    exec "$@"
' -- "$@"
