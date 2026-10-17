Two workflows in the current directory are meant to run on the ComfyUI instance your tools are connected to, and neither can as it is: `T10-api.json`, in API format, and `T10-ui.json`, in the format ComfyUI's editor saves. Find what each one needs that the instance doesn't have, and prepare what it would take to make them runnable, for someone else to apply. Don't change the instance: don't install, download or run anything.

1. Write `results/T10.json`, one JSON object with these keys:
   - `workflows`: an object keyed by each workflow's file name. Each value has three lists, empty where there is nothing:
     - `missing_models`: each model file the workflow names that the instance doesn't have, as the workflow names it;
     - `missing_node_classes`: each node class the workflow uses that the instance doesn't have;
     - `model_value_changes`: each model the instance has, but not under the name the workflow gives it, as `{"from": <the value in the workflow>, "to": <the value that names that file on this instance>}`.
   - `comfy_yaml_models`: entries for the `models` list of a `comfy.yaml` manifest that would fetch the model files the instance lacks, one file for each. `comfy.schema.json`, in the current directory, is that manifest's JSON Schema, and the entries must be valid against it.
   - `custom_nodes`: the custom-node packs the instance lacks, as a ComfyUI-Manager snapshot lists them: `git_custom_nodes` maps a pack's git repository URL to `{"hash": <the commit>, "disabled": false}`, and `cnr_custom_nodes`, only if one is needed, maps a Comfy registry id to its version.
2. Write each workflow back with every `model_value_changes` fix applied and nothing else changed, in the format it is in now, as `results/T10-api.json` and `results/T10-ui.json`.

Take a model's or a pack's source only from what the workflows say; don't guess one.
