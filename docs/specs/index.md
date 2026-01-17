# Specs

Specification-driven design docs for key parts of the ComfyUI Docker project.

## Current Specs

- **[Custom Nodes Snapshot Spec](custom-nodes-snapshot-spec.md)** – specification for how the Complete image manages and installs its bundled custom nodes using ComfyUI’s CLI and snapshot support.

## Candidate Future Specs

These are suggested next specs to introduce as work is prioritized:

- **Complete Image Spec** – high-level contract for the `complete` image (features, performance expectations, supported profiles, and user-facing guarantees).
- **Data & Models Layout Spec** – canonical definition of `/data`, `/models`, workflows, and how containers map host storage.
- **Deployment Profiles Spec** – supported profiles (CPU/CUDA/ future ROCm/ARM), image tags, and cloud template expectations.
- **Security & Configuration Spec** – authentication options, token handling for model providers, and configuration surface via environment variables.

