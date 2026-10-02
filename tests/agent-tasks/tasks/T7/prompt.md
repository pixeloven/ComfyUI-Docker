In `pack/`, write a ComfyUI custom node pack with ComfyUI's V3 node API (`comfy_api.latest`, registered through a `comfy_entrypoint` function in the pack's `__init__.py`, with no `NODE_CLASS_MAPPINGS` anywhere). It has two nodes:

- `T7Reverse`: category `t7`, one required STRING input named `text`, and one STRING output: the input reversed.
- `T7Show`: category `t7`, an output node with one required STRING input named `text`, which it displays in the UI as text (its result's `ui` carries `text`).

Give the pack a `pyproject.toml` that the Comfy registry would accept: `[project]` with `name` and `version`, and `[tool.comfy]` with `PublisherId`.

Then make the running ComfyUI load the pack without recreating its container, and make sure both nodes are registered from your pack and that ComfyUI logged no error loading it.

Run one workflow in which `T7Reverse` gets `text` = `harness` and its output goes to `T7Show`, and wait until it has finished. Run it after your last restart: a restart empties `/history`, so check anything after it without restarting (`./dev-check.sh --no-restart`).

Write `results/T7.json` as one JSON object with exactly these keys:

- `class`: `"T7Reverse"`
- `prompt_id`: the prompt id ComfyUI returned for that run
