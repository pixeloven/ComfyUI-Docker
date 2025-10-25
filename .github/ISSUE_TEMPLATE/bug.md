---
name: Bug Report
about: Report a bug or issue with ComfyUI Docker
title: ""
labels: bug
assignees: ""
---

<!--  PLEASE FILL THIS OUT, IT WILL MAKE ALL OF OUR LIVES EASIER -->
<!--  we promise we read every issue, even if your cat exploded -->

**Describe the bug**

<!--  tried to start the container, my GPU caught fire and my cat is now a husky -->

**Deployment Profile**

Which Docker Compose profile are you using?
- [ ] Core (core-cuda)
- [ ] Core CPU (core-cpu)
- [ ] Complete (complete-cuda)
- [ ] Other/Custom: _______

**Hardware / Software**

- OS: [e.g. Windows 11 / Ubuntu 24.04 / macOS Sequoia]
- OS version: <!--  windows: run `winver` | ubuntu: run `lsb_release -d` | mac: run `sw_vers` -->
- WSL version (if applicable): <!-- get using `wsl -l -v` -->
- Docker version: <!--  run: `docker version` -->
- Docker Compose version: <!--  run: `docker compose version` -->
- Image version: <!-- tag, commit sha, or "latest from main" -->
- GPU: [e.g. NVIDIA RTX 4090 / AMD Radeon / None (CPU)]
- VRAM: [e.g. 24GB / N/A]
- RAM: [e.g. 32GB]
- CUDA version (if NVIDIA): <!--  run: `nvidia-smi` and check top right -->

**Container & Build Info**

- Are you using pre-built images from GHCR or building locally?
- If building: Which bake target? <!--  e.g. `docker buildx bake core-cuda` -->
- If using GHCR: Which image tag? <!--  e.g. `ghcr.io/pixeloven/comfyui-docker/core:cuda-latest` -->

**Environment Configuration**

Which custom environment variables are you using (if any)?
```bash
# Paste your docker-compose command or relevant .env vars here
# e.g. COMFY_PORT=8188, CLI_ARGS="--lowvram", etc.
```

**Steps to Reproduce**

1. Start with '...'
2. Run command '....'
3. Access '....'
4. See error

**Expected behavior**

<!--  what SHOULD happen (e.g. "container should start and serve ComfyUI on port 8188") -->

**Actual behavior**

<!--  what ACTUALLY happened (e.g. "container crashes with CUDA out of memory") -->

**Logs**

<!--  Run: `docker compose logs core-cuda` (or your profile) and paste relevant output -->
```
paste logs here
```

**Additional context**

Any other context about the problem here. If applicable, add screenshots, workflow files, or custom node configurations.
