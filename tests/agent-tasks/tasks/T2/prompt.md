Install the custom node pack ComfyUI-Custom-Scripts into the ComfyUI instance your tools are connected to, pinned to commit `aac13aa7ce35b07d43633c3bbe654a38c00d74f5`:

- repository: https://github.com/pythongosssss/ComfyUI-Custom-Scripts
- Comfy registry id `comfyui-custom-scripts`, version `1.2.5`, which was published from that commit

Restart ComfyUI if the new nodes need a restart to load.

Then run a workflow that uses the pack's Math Expression node (class `MathExpression|pysssss`) to evaluate the expression `6 * 7`, and wait until it has finished. Report the value it produced.
