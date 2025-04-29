- [] Fix Mappings for models `/data/models` and `data/config/comfy/models` the later is created by ComfyManager
- [] Add out of the box support for onnx but make it configurable (optional) not backed into the image
- [] Run everything in an venv
- [] Update docker-compose to be a more readable
- [] Add support for swarm
- [] Pin / configurable versions
- [] rocm / zluda support
- [] persistant vol for custom extensions
- [] generally better workflow vol mappings
- [] Update download to use a manifest / mapping.
- [] Create a APP for managing manifests, output, etc
- [] Drop docker support for A111 build alternative using ComfyUI wtih preset workflows in rep

```
 WAS Node Suite: Image file saved to: /data/output/2025-04-29/1745898150_character_refined_0001.png
comfy-1  | Failed to find /data/config/comfy/custom_nodes/comfyui_controlnet_aux/ckpts/lllyasviel/Annotators/body_pose_model.pth.
comfy-1  |  Downloading from huggingface.co
comfy-1  | cacher folder is /tmp, you can change it by custom_tmp_path in config.yaml
comfy-1  | /home/comfy/.local/lib/python3.11/site-packages/huggingface_hub/file_download.py:896: FutureWarning: `resume_download` is deprecated and will be removed in version 1.0.0. Downloads always resume when possible. If you want to force a new download, use `force_download=True`.
comfy-1  |   warnings.warn(
comfy-1  | /home/comfy/.local/lib/python3.11/site-packages/huggingface_hub/file_download.py:933: UserWarning: `local_dir_use_symlinks` parameter is deprecated and will be ignored. The process to download files to a local folder has been updated and do not rely on symlinks anymore. You only need to pass a destination folder as`local_dir`.
comfy-1  | For more details, check out https://huggingface.co/docs/huggingface_hub/main/en/guides/download#download-files-to-local-folder.
comfy-1  |   warnings.warn(
comfy-1  | [Errno 2] No such file or directory: '/tmp/ckpts'
comfy-1  | model_path is /data/config/comfy/custom_nodes/comfyui_controlnet_aux/ckpts/lllyasviel/Annotators/body_pose_model.pth
comfy-1  | Failed to find /data/config/comfy/custom_nodes/comfyui_controlnet_aux/ckpts/lllyasviel/Annotators/hand_pose_model.pth.
comfy-1  |  Downloading from huggingface.co
comfy-1  | cacher folder is /tmp, you can change it by custom_tmp_path in config.yaml
comfy-1  | [Errno 2] No such file or directory: '/tmp/ckpts'
comfy-1  | model_path is /data/config/comfy/custom_nodes/comfyui_controlnet_aux/ckpts/lllyasviel/Annotators/hand_pose_model.pth
comfy-1  | Failed to find /data/config/comfy/custom_nodes/comfyui_controlnet_aux/ckpts/lllyasviel/Annotators/facenet.pth.
comfy-1  |  Downloading from huggingface.co
comfy-1  | cacher folder is /tmp, you can change it by custom_tmp_path in config.yaml
comfy-1  | [Errno 2] No such file or directory: '/tmp/ckpts'
comfy-1  | model_path is /data/config/comfy/custom_nodes/comfyui_controlnet_aux/ckpts/lllyasviel/Annotators/facenet.pth