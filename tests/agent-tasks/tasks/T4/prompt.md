The file `T4-workflow.json` in the current directory is a ComfyUI workflow in API format. Submit it to the ComfyUI instance your tools are connected to and run it. Do not modify or repair it.

Then write `results/T4.json`, reporting what actually happened, as one JSON object with exactly these keys:

- `succeeded`: a JSON boolean, `true` only if ComfyUI accepted the workflow and it ran to completion
- `node_id`: the id of the node ComfyUI reported a problem with, as a string, or `null`
- `error_type`: the error type ComfyUI returned, or `null`
- `error_message`: the error message ComfyUI returned, or `null`
- `details`: any further detail ComfyUI returned, or `null`

Report ComfyUI's own error text, not a paraphrase.
