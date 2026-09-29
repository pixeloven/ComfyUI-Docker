# Adding models and nodes

A workflow often needs something the instance doesn't have: a checkpoint, a
LoRA, a node pack. **Don't install it.** In a deployment built from this
repository, what an instance holds is declared in files a human reviews, and an
agent's job is to propose the change to those files.

## What to do instead

1. **Find out exactly what's missing.** Check node classes against the live
   instance (`/object_info`, or the relay's `node_search` and `node_describe`)
   and models against what's on disk (`/models/<folder>`, or `model_list`). For
   a template, the relay's `template_get` reports `missing_nodes`,
   `missing_models` and `missing_inputs` directly.
2. **Propose the change**, for a human to apply:
   - **A model** goes in the deployment's `comfy.yaml`, followed by a
     regenerated lock (`comfyctl fetch resolve`). Give its source (`hf:`,
     `gh:`, `civitai:` or a URL with its `sha256`), the file, and the folder
     it belongs in (`install: models/<folder>/`). The `comfy-manifest` topic
     covers the format.
   - **A node pack** goes in the `custom_nodes` section of `comfy-lock.yaml`,
     pinned to a version or commit. Name the pack's repository and the class
     you need from it. `comfyctl fetch` fetches models only, so this entry
     records the request for whoever deploys the instance.
3. **Say what the workflow needs it for**, so the reviewer can judge it: which
   node, which input, and the model's license if it restricts use.

Never suggest installing through ComfyUI-Manager, `git clone` into
`custom_nodes`, `comfy node install`, `pip install`, or a direct download into
the models directory. Each works once, on one instance, and the next rebuild
or replica loses it. The comfyrelay sidecar refuses to install anything
(see the `relay-limits` topic).

## The subfolder gotcha

ComfyUI lists a model by its path **relative to its folder type**. A
checkpoint at `models/checkpoints/sdxl/sd_xl_base_1.0.safetensors` is offered
as `sdxl/sd_xl_base_1.0.safetensors`, not by its bare file name.

A workflow or template that names the bare file therefore fails, even though
the file is on disk. ComfyUI rejects the loader's input with
`value_not_in_list`, and its details list the values it would accept. The fix
is to change the loader's value to the listed path, not to move or copy the
file.

- The relay's template check reports this case separately, as
  `models_need_value_change`, with `found_at` giving the path to use.
- `model_list` shows files the same way the loaders list them, with the
  subfolder included.
- When you propose a manifest entry, the folder in `install:` decides the
  path. `install: models/checkpoints/` gives the bare name, and
  `install: models/checkpoints/sdxl/` gives `sdxl/<file>`.

## Folder types

The folder a model goes in decides which loaders offer it: `checkpoints` for
full checkpoints, `diffusion_models` for a bare diffusion model, `loras`,
`vae`, `text_encoders`, `clip_vision`, `controlnet`, `upscale_models`, and
more. `/models` on the instance (or `model_list`) lists the folder types that
instance knows. A template's model entries name their folder in `directory`.
