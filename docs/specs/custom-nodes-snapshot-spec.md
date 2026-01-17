# Custom Nodes Snapshot Spec

Specification for how the **Complete** image manages and installs its bundled custom nodes using ComfyUI’s native CLI and snapshot support.

## 1. Overview

The Complete image ships with 13+ curated custom nodes. Historically these were installed by runtime bash scripts on first container startup. This spec formalizes a **snapshot-based, build-time installation** strategy using `comfy-cli`.

The intent is to:
- Make custom node installation **reproducible** and **version-controlled**
- Avoid bespoke bash installers in favor of **official ComfyUI tooling**
- Move work from **container startup** to **image build time** for faster, more predictable launches

## 2. Scope

In scope:
- How the Complete image defines and installs its default set of custom nodes
- Use of `comfy node save-snapshot` / `comfy node restore-snapshot`
- Location and format of the production snapshot file
- Requirements for updating and maintaining the snapshot

Out of scope (for this spec):
- Per-user or per-workspace custom nodes beyond the baked-in defaults
- Full data/model directory layout (covered by a future Data & Models Layout Spec)
- Cloud-specific deployment concerns (covered by a future Deployment Profiles Spec)

## 3. Goals and Non-Goals

### Goals

- **G1 – Reproducible installs:** Custom nodes for the Complete image are fully defined by a committed snapshot file.
- **G2 – Build-time installation:** All default custom nodes are installed during Docker image build, not at runtime.
- **G3 – No bespoke installers:** Remove the need for numbered runtime install scripts and custom library functions.
- **G4 – Simple upgrades:** Updating the node set is a matter of regenerating and reviewing an updated snapshot file.
- **G5 – Stable base experience:** A published Complete tag always corresponds to a specific, reviewable snapshot.

### Non-Goals

- **N1:** Providing a UI or API for end users to manage custom nodes is out of scope.
- **N2:** Supporting multiple built-in “node bundles” per image is out of scope; this spec covers only the default Complete bundle.
- **N3:** Automatically discovering or installing nodes from workflows at runtime is out of scope.

## 4. Functional Requirements

**F1 – Snapshot definition**
- A file `services/comfy/complete/production-snapshot.json` defines:
  - The ComfyUI base revision (`"comfyui": "<branch|commit>"`)
  - The full set of baked-in custom nodes with URLs and commit hashes
  - Any pip dependencies required by those nodes

**F2 – Build-time restore**
- The Complete Dockerfile must restore the snapshot during build:
  - Copy `production-snapshot.json` into `/app/production-snapshot.json`
  - Run `comfy node restore-snapshot /app/production-snapshot.json` as part of the image build

**F3 – Runtime behavior**
- At container startup:
  - No custom-node installation or update logic should run
  - Startup scripts should assume the baked-in nodes already exist

**F4 – Deterministic builds**
- A build that uses the same:
  - Base image
  - `production-snapshot.json`
  - Extra requirements file
- Must result in the same set of custom nodes and pip dependencies.

**F5 – Explicit node list**
- The snapshot must represent at least the current 13 curated nodes (platform essentials, workflow enhancers, detection/segmentation, image enhancers, control systems, distribution systems).

## 5. Non-Functional Requirements

**NF1 – Performance**
- Container startup time for the Complete image must not include any custom-node installation costs beyond normal ComfyUI initialization.

**NF2 – Security**
- No git clone or arbitrary code execution for node installation should happen at runtime; all such operations should occur at build time.

**NF3 – Maintainability**
- Updating nodes should not require editing bash scripts; the primary artifact to review is `production-snapshot.json`.

**NF4 – Observability**
- Builds should log snapshot restoration steps and clearly fail if `comfy node restore-snapshot` fails.

## 6. Design

### 6.1 Snapshot file location and contents

- Source of truth for baked-in custom nodes:
  - `services/comfy/complete/production-snapshot.json`
- Expected high-level structure:
  - `"comfyui"`: commit or branch used when the snapshot was taken
  - `"custom_nodes"`: map of git URLs to:
    - URL
    - Commit hash (or branch, e.g. `"main"` initially)
    - Disabled flag
  - `"pips"`: version-pinned pip dependencies required by installed nodes

### 6.2 Dockerfile integration (Complete image)

The Complete Dockerfile for CUDA should:

- Copy the snapshot file into the image:
  - `COPY --chown=comfy:comfy ./production-snapshot.json /app/production-snapshot.json`
- Restore the snapshot during build:
  - Activate the virtual environment
  - `cd /app`
  - Run `comfy node restore-snapshot /app/production-snapshot.json`
- Install `extra-requirements.txt` after snapshot restoration if additional wheels are required.

This ensures the resulting image already contains all required custom nodes in `/app/custom_nodes` when it is published.

### 6.3 Startup behavior

The Complete startup script must:

- Avoid checking for or installing custom nodes
- Avoid `.post_install_done` markers for node installation
- Focus on:
  - `comfy env`
  - `comfy tracking disable`
  - `comfy launch -- --listen --port $COMFY_PORT $CLI_ARGS`

If migration scripts previously handled directory setup or sample workflows, those concerns should be addressed separately from node installation.

## 7. Alternatives Considered (Comparison of Solutions)

The following alternatives were evaluated before selecting build-time snapshot restoration as the primary approach.

### Option A – Runtime Snapshot Restoration

**Description**
- Keep `production-snapshot.json` in the image and run:
  - `comfy node restore-snapshot /app/production-snapshot.json`
  - On first container startup, guarded by a `.post_install_done` marker.

**Pros**
- Minimal changes to existing architecture that already uses runtime scripts.
- Uses the same stable snapshot format and official ComfyUI tooling.
- Easy to reason about when experimenting locally.

**Cons**
- Slower first startup because installation still happens at runtime.
- Requires runtime git and network access for node installation.
- Continues to rely on “first-run” logic and marker files.

### Option B – Build-Time Snapshot Restoration (Chosen)

**Description**
- Install all custom nodes during Docker build using `production-snapshot.json`.
- The runtime image contains preinstalled nodes; startup scripts do not perform installation.

**Pros**
- Zero runtime installation overhead; startup is fast and predictable.
- No git or package installation at container runtime (better security and reliability).
- Clear, reviewable artifact (`production-snapshot.json`) defines the node set.
- Matches typical expectations for “batteries-included” production images.

**Cons**
- Updating nodes requires rebuilding images.
- Snapshot maintenance becomes part of the release process.

### Option C – User-Provided Snapshots

**Description**
- Allow overriding the snapshot file via environment variables and/or bind mounts.
- Example: `COMFY_SNAPSHOT_FILE` points to a mounted snapshot, restored on container startup.

**Pros**
- Maximum flexibility for advanced users and teams.
- Enables different node bundles without rebuilding images.

**Cons**
- More complex behavior to document and support.
- Reintroduces runtime installation costs and network dependencies.
- Increases variability of deployed environments.

**Status**
- Not included in the baseline spec.
- May be introduced later as an **opt-in advanced feature**, provided core behavior (Option B) remains stable and well-documented.

## 8. Maintenance and Workflow

High-level workflow for maintaining `production-snapshot.json`:

1. **Generate / Update Snapshot**
   - Use a development environment (or CI job) with the desired node set installed.
   - Run `comfy node save-snapshot --output production-snapshot.json`.
2. **Review Changes**
   - Inspect diffs in `production-snapshot.json` (new nodes, updated hashes, changed pip deps).
3. **Validate Build**
   - Build the Complete image locally or in CI.
   - Confirm custom nodes are present and ComfyUI starts successfully.
4. **Publish**
   - Merge snapshot changes and publish new image tags as appropriate.

Future CI improvements (outside the strict scope of this spec) may automate snapshot regeneration and PR creation on a schedule.

## 9. Open Questions

- Should we pin all custom node hashes immediately, or start with branch-based refs (`"main"`) and pin over time?
- Do we want a formal retention policy for old snapshots (e.g., keeping previous versions for rollback)?
- Should there be a lightweight runtime check that warns if the snapshot and installed nodes diverge significantly?

