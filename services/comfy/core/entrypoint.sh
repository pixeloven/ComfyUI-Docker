#!/bin/bash
set -e

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

# Create group if GID doesn't exist
if ! getent group "$PGID" > /dev/null 2>&1; then
    groupadd -g "$PGID" "$USERNAME"
fi
GROUP_NAME=$(getent group "$PGID" | cut -d: -f1)

# Create user if UID doesn't exist
if ! getent passwd "$PUID" > /dev/null 2>&1; then
    useradd -u "$PUID" -g "$PGID" -d /app -s /bin/bash -M "$USERNAME"
fi

# =============================================================================
# Directory Ownership
# =============================================================================

# Set ownership of critical application directories only
# Mounted volumes retain host ownership (intended behavior)
chown "$PUID:$PGID" /app /app/ComfyUI

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
