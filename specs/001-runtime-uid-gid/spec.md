# Feature Specification: Runtime UID/GID Support

**Feature Branch**: `001-runtime-uid-gid`
**Created**: 2026-01-30
**Status**: Complete
**Input**: User description: "Runtime UID/GID support"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Custom UID/GID Container Startup (Priority: P1)

As a system administrator deploying ComfyUI on a shared server, I need to run the container with a specific UID/GID that matches my host user (e.g., 3000:3000) so that files created in mounted volumes have correct ownership and I can manage them without permission issues.

**Why this priority**: This is the core value proposition. Without this, users with non-default UIDs cannot use the container reliably, and PyTorch/ComfyUI operations fail with `getpwuid` errors.

**Independent Test**: Can be fully tested by running the container with PUID=3000/PGID=3000 and verifying the container starts without errors and creates files with correct ownership.

**Acceptance Scenarios**:

1. **Given** a host user with UID 3000 and GID 3000, **When** I start the container with PUID=3000 and PGID=3000 environment variables, **Then** the container starts successfully and runs ComfyUI as UID 3000:GID 3000.

2. **Given** a running container with custom UID/GID, **When** ComfyUI creates output files in mounted volumes, **Then** those files are owned by the specified PUID:PGID on the host filesystem.

3. **Given** a container started with custom UID/GID, **When** PyTorch initializes its cache, **Then** no `KeyError: 'getpwuid(): uid not found'` errors occur.

---

### User Story 2 - Default UID/GID Backward Compatibility (Priority: P2)

As an existing user with standard deployments, I need the container to work exactly as before when I don't specify PUID/PGID so that my existing docker-compose configurations continue to function without modification.

**Why this priority**: Backward compatibility is essential to avoid breaking existing deployments. Most users have UID 1000 and should not need to change anything.

**Independent Test**: Can be fully tested by running the container without PUID/PGID variables and verifying it behaves identically to current behavior (UID 1000:GID 1000).

**Acceptance Scenarios**:

1. **Given** a docker-compose.yml without PUID/PGID variables, **When** I start the container, **Then** the container runs with UID 1000:GID 1000 (default behavior).

2. **Given** an existing deployment using the current image, **When** I upgrade to the new image without changing my configuration, **Then** all functionality continues to work as expected.

---

### User Story 3 - Security-Compliant Non-Root Execution (Priority: P3)

As a security-conscious operator, I need to verify that the container runs application processes as the specified non-root user so that I can meet container security policies that prohibit root-running applications.

**Why this priority**: Security compliance is important but is a verification requirement rather than a functional change. The implementation naturally provides this.

**Independent Test**: Can be fully tested by inspecting the running container's process list and confirming ComfyUI runs as the specified non-root user.

**Acceptance Scenarios**:

1. **Given** a running container with any PUID/PGID configuration, **When** I inspect the process list inside the container, **Then** ComfyUI and related processes run as the specified non-root user.

2. **Given** a container started with PUID=1000, **When** I run `ps aux` inside the container, **Then** no application processes show root as the user (entrypoint initialization excluded).

---

### Edge Cases

- What happens when PUID/PGID matches an existing system user in the container image?
  - The system reuses the existing user/group without error.

- What happens when PUID=0 (root) is specified?
  - The container runs as root, which is allowed but not recommended. A warning should be logged.

- What happens when only PUID is specified without PGID (or vice versa)?
  - The unspecified value defaults to 1000.

- What happens when the UID/GID is extremely high (e.g., 65534)?
  - The system creates the user/group with that ID; no special handling required as Linux supports UIDs up to 2^32-1.

- What happens when mounted volumes have restrictive permissions?
  - The entrypoint only adjusts ownership of critical application directories, not mounted volumes. Users must ensure volume permissions are appropriate.

- What happens when PUID/PGID is invalid (negative, non-numeric, or out of range)?
  - The container MUST fail to start with a clear error message indicating the invalid value. No fallback to defaults.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Container MUST accept PUID and PGID environment variables to specify runtime user/group IDs
- **FR-002**: Container MUST default PUID to 1000 and PGID to 1000 when not specified
- **FR-003**: Container MUST create a user entry in /etc/passwd for the specified UID if it does not exist
- **FR-004**: Container MUST create a group entry in /etc/group for the specified GID if it does not exist
- **FR-005**: Container MUST run ComfyUI and related application processes as the specified UID:GID
- **FR-006**: Container MUST set ownership of critical application directories (/app, /app/ComfyUI) to the runtime UID:GID
- **FR-007**: Container MUST properly drop privileges from root to the target user using a secure method
- **FR-008**: Container MUST ensure no root shell process remains in the process tree after initialization
- **FR-009**: Container MUST support reusing existing users/groups when PUID/PGID matches an already-defined ID
- **FR-010**: Container MUST validate PUID/PGID values and fail startup with a clear error message if values are invalid (negative, non-numeric, or out of valid range)
- **FR-011**: Container MUST log a single startup confirmation line showing the effective UID:GID (format: "Starting with UID:GID = X:Y")

### Key Entities

- **Runtime User**: The dynamically created or reused user account with the specified UID, used to run application processes
- **Runtime Group**: The dynamically created or reused group with the specified GID, assigned as the primary group for the runtime user
- **Critical Directories**: Application directories that require write access at runtime (/app, /app/ComfyUI) and must be owned by the runtime user

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Container starts successfully within 30 seconds when provided any valid PUID/PGID combination (1-65534)
- **SC-002**: 100% of files created by ComfyUI in mounted volumes are owned by the specified PUID:PGID
- **SC-003**: Zero `getpwuid` or user-not-found errors occur during PyTorch/ComfyUI initialization with custom UID/GID
- **SC-004**: Existing deployments without PUID/PGID configuration continue to work with zero changes required
- **SC-005**: All three deployment profiles (core-cuda, complete-cuda, core-cpu) support the runtime UID/GID feature

## Clarifications

### Session 2026-01-30

- Q: When the entrypoint script fails to create the user/group (e.g., invalid PUID value like negative number or non-numeric string), what should happen? → A: Container fails to start with clear error message
- Q: What level of logging should the entrypoint provide during user/group setup? → A: Minimal (single line: "Starting with UID:GID = X:Y")
- Q: Should the implementation support alternative privilege-dropping tools (su-exec) or strictly require gosu? → A: Require gosu only

## Assumptions

- Users have appropriate permissions to run Docker containers
- Host filesystem permissions on mounted volumes are compatible with the specified UID/GID
- The gosu utility is required and must be installed in the container image for secure privilege dropping (no alternatives supported)
- Container startup occurs with root privileges to allow user creation and privilege dropping
