# Custom Nodes Migration (Legacy Notes)

This document previously contained a detailed, step-by-step migration plan for moving from runtime bash scripts to native ComfyUI snapshot-based custom node installation.

The project is now moving to **SPEC-driven development**, and this detailed plan has been **superseded** by a focused specification.

## Current Source of Truth

- **Primary spec:** ../specs/custom-nodes-snapshot-spec.md  
  Defines goals, requirements, design, and alternatives for how the Complete image manages bundled custom nodes.

## Relevant Research (Retained)

### ComfyUI CLI Capabilities (Summary)

Verified `comfy-cli` commands used in the migration:

- `comfy node install <name|url>` – Install custom nodes from registry or git
- `comfy node update all` – Update all installed nodes
- `comfy node save-snapshot --output <file.json|.yaml>` – Save installation state
- `comfy node restore-snapshot <file.json|.yaml>` – Restore from snapshot
- `comfy node install-deps --deps <file.json>` – Install from dependency spec
- `comfy node install-deps --workflow <file.json|.png>` – Install workflow dependencies
- `comfy node deps-in-workflow --workflow <file> --output <deps.json>` – Extract deps

### Snapshot Format (ComfyUI-Manager) – High Level

- Tracks:
  - ComfyUI commit hash
  - Custom nodes (URLs, commit hashes, disabled state)
  - File-based custom nodes
  - Pip dependencies with versions
- Format is:
  - Human-readable (JSON/YAML)
  - Version-controllable
  - Stable and supported by official tooling

The **comparison of migration options and the chosen approach** (runtime vs build-time vs user-provided snapshots) is now captured in the “Alternatives Considered” section of the spec rather than as a standalone project plan.

## See Also

- ../specs/custom-nodes-snapshot-spec.md
- repository-analysis.md

