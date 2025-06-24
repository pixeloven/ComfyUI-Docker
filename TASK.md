# Tasks
- [] Fix Mappings for models `/data/models` and `data/config/comfy/models` the later is created by ComfyManager
- [] Add out of the box support for onnx but make it configurable (optional) not backed into the image
- [] Run everything in an venv
- [] Update docker-compose to be a more readable
- [] Add support for swarm
- [] Pin / configurable versions
- [] rocm / zluda support
- [] persistant vol for custom extensions
- [] generally better workflow vol mappings
- [] Update setup to use a manifest / mapping.
- [] Create a APP for managing manifests, output, etc
- [] Drop docker support for A111 build alternative using ComfyUI wtih preset workflows in rep

# Managing Worfklows / Models
- [] Create private repo in github save all workflow data there.
- [] versioning of workflows
- [] Descriptions and readmes for models - similar to stability matrix but standalone or as part of comfy plugin
- [] Move this into harmony and restructure that project - this is no longer just docker for stable


## Things to fix
- Fix Mappings for models `/data/models` and `data/config/comfy/models` the later is created by ComfyManager
- Comfy Manager downloads to incorrect nested folder /data/data/models/*

## Things to improve
- Move plugins-requirements.txt install to entrypoint or just provide ability to rerun after container is created.
- Figure out difference from Comfy Manager and the other Manager - auto install comfy manager for now
- Move /output to /data/output
- Get default CLI args to work correctly
- Get vol mount for extra_model_paths to work
- Port should be configurable at run time
- Auto setup script for ipadapter https://github.com/cubiq/ComfyUI_IPAdapter_plus
- Auto configuration and PuLID and InstantID and FaceID
- Auto configuration and setup for onnx and sage

# Should also decide whether this repo is just for image gen in stable or more general AI workflow since some of thje tools also blur and support audio, text etc