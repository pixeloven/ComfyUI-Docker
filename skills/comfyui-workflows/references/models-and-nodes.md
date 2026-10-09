# Adding models and nodes

A workflow often needs something the instance doesn't have: a checkpoint, a
LoRA, a node pack. **Don't install it.** In a deployment built from this
repository, what an instance holds is declared in files a human reviews, and an
agent's job is to propose the change to those files.

## What to do instead

1. **Find out exactly what's missing.** Check node classes against the live
   instance (`/object_info`) and models against what's on disk
   (`/models/<folder>`). The relay's `node_search`, `node_describe` and
   `model_list` do the same, and its `template_get` reports a template's
   `missing_nodes`, `missing_models` and `missing_inputs` directly. *(needs the comfyrelay sidecar)*
2. **Propose the change**, for a human to apply:
   - **A model** goes in the deployment's `comfy.yaml`, followed by a
     regenerated lock (`comfyctl fetch resolve`). Give its source (`hf:`,
     `gh:`, `civitai:` or a URL with its `sha256`), the file, and the folder
     it belongs in (`install: models/<folder>/`). The `comfy-manifest` topic
     covers the format.
   - **A node pack** goes in the `custom_nodes` section of `comfy-lock.yaml`,
     pinned to a commit (*A `custom_nodes` entry*, below, has the fields).
     Name the pack's repository and the class you need from it.
     `comfyctl fetch` fetches models only, so this entry records the request
     for whoever deploys the instance.
3. **Say what the workflow needs it for**, so the reviewer can judge it: which
   node, which input, and the model's license if it restricts use.

Never suggest installing through ComfyUI-Manager, `git clone` into
`custom_nodes`, `comfy node install`, `pip install`, or a direct download into
the models directory. Each works once, on one instance, and the next rebuild
or replica loses it.

The comfyrelay sidecar refuses to install anything (see the `relay-limits`
topic). *(needs the comfyrelay sidecar)*

## A `custom_nodes` entry

The section has comfy-cli's shape. A pack from git goes under
`git_custom_nodes`, keyed by its repository URL, with the full commit SHA it's
pinned to in `hash`. This is the entry in this repository's own lock:

```yaml
custom_nodes:
  comfyui: 8f40b43e0204d5b9780f3e9618e140e929e80594
  git_custom_nodes:
    https://github.com/kijai/ComfyUI-KJNodes:
      disabled: false
      hash: a40cf52c4779454451c4480c95947045e3f31c94
```

A pack from the Comfy Registry goes under `cnr_custom_nodes` instead, as its
registry id mapped to a released version. That is the map ComfyUI-Manager
writes in a snapshot (`get_current_snapshot`, which records a registry pack
there only when its version isn't `nightly`, `latest` or `unknown`):

```yaml
custom_nodes:
  cnr_custom_nodes:
    <registry id>: <version>
```

- **Propose only the pack's entry**, under `git_custom_nodes` or
  `cnr_custom_nodes`. `comfyui` beside them isn't part of any pack's entry:
  leave it as the lock has it. If the lock has no `custom_nodes` section yet,
  propose the pack's map alone and don't add `comfyui`.
- **`hash` is a full commit SHA**, not a branch or a tag, so the pin can't move.
  A registry entry pins a released version, never `nightly` or `latest`.
- **A `cnr_custom_nodes` map is the whole set.** Restoring a ComfyUI-Manager
  snapshot disables any installed registry pack the map doesn't list. Add to
  an existing map. If you start one, say in the proposal that it lists only
  this pack.
- **This section is the part of the lock written by hand.**
  `comfyctl fetch resolve` writes only `auth` and `models`, so a lock
  regenerated with it has no `custom_nodes` section. Carry the section over
  when you regenerate.
- `comfyctl fetch check` accepts any object here, and nothing in `comfyctl`
  reads it.

## The subfolder gotcha

ComfyUI lists a model by its path **relative to its folder type**. A
checkpoint at `models/checkpoints/sdxl/sd_xl_base_1.0.safetensors` is offered
as `sdxl/sd_xl_base_1.0.safetensors`, not by its bare file name.

A workflow or template that names the bare file therefore fails, even though
the file is on disk. ComfyUI rejects the loader's input with
`value_not_in_list`, and its details list the values it would accept. The fix
is to change the loader's value to the listed path, not to move or copy the
file.

- `/models/<folder>` lists files the same way the loaders do, with the
  subfolder included.
- The relay's template check reports this case separately, as
  `models_need_value_change`, with `found_at` giving the path to use. *(needs the comfyrelay sidecar)*
- When you propose a manifest entry, the folder in `install:` decides the
  path. `install: models/checkpoints/` gives the bare name, and
  `install: models/checkpoints/sdxl/` gives `sdxl/<file>`.

## Folder types

The folder a model goes in decides which loaders offer it: `checkpoints` for
full checkpoints, `diffusion_models` for a bare diffusion model, `loras`,
`vae`, `text_encoders`, `clip_vision`, `controlnet`, `upscale_models`, and
more. `/models` on the instance lists the folder types that instance knows. A
template's model entries name their folder in `directory`.
