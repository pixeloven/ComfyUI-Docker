# Errors and validation

A workflow can fail when ComfyUI checks it on submit (section 2), or while it
runs (section 3). Each point catches different mistakes, so knowing which one
spoke tells you where to look. The relay adds a check before submitting
(section 1). *(needs the comfyrelay sidecar)*

## 1. Before submitting: `workflow_validate` (comfyrelay)

*Needs the comfyrelay sidecar.*

**`valid: true` doesn't mean ComfyUI will accept the graph.** `workflow_validate`
doesn't check input types or values. A link that carries the wrong type, such
as a `LoadImage` mask (output 1) wired into `SaveImage`'s `images`, passes it
with `valid` and `runnable` both true. (`runnable` means only that
`workflow_run` will submit it.) That graph then fails at `workflow_run` with
`workflow_rejected`, and ComfyUI's `return_type_mismatch` names the node and
input (section 2). Only submitting a graph with `workflow_run` tells you
whether ComfyUI accepts it, and that also runs it: there is no dry run.

ComfyUI has no dry run, so the relay checks only what can be known without
submitting the graph, against the live `/object_info`:

- the graph is in API format (a UI save file, or a whole `/prompt` body, is
  `invalid_workflow`);
- every `class_type` exists on this instance (`missing_node_type`, with near
  names);
- every link points at a node in the graph and an output that node has
  (`bad_linked_input`, `linked_node_missing`, `linked_output_missing`);
- at least one node is an output node (`prompt_no_outputs`);
- no node is a partner-API node, which `workflow_run` refuses;
- a node that no output depends on gets the warning `not_connected_to_output`,
  since ComfyUI won't run it.

It does **not** check input types, link types, values, required inputs or
COMBO choices. Those are ComfyUI's checks, and they run only when the graph is
submitted. The relay doesn't copy them, because a copy refused graphs ComfyUI
accepts.

## 2. On submit: ComfyUI's `/prompt` checks

When `/prompt` refuses a graph it answers HTTP 400 with an `error` and a
`node_errors` object keyed by node id. Each node's entry lists its errors, each
with a `type`, a `message`, `details` and `extra_info` (often the input name).

The relay's `workflow_run` passes this on as `workflow_rejected`, and flattens
it into `type`, `node_id`, `class_type`, `input`, `details`, `expected` and
`got`. *(needs the comfyrelay sidecar)*

The error types you'll meet most:

| `type` | Means | Usually fix by |
|---|---|---|
| `required_input_missing` | a required input has no value or link | adding it; the node's definition (`/object_info/<class>`) marks required inputs |
| `value_not_in_list` | a COMBO value isn't among the allowed ones | using a listed value. For a model, check the subfolder path (see `models-and-nodes`) |
| `return_type_mismatch` | a link carries the wrong type, such as a MASK into an IMAGE input | linking the right output index |
| `value_smaller_than_min` / `value_bigger_than_max` | a number is out of range | using the min, max and step from the node's definition |
| `invalid_input_type` | a value can't be converted to the input's type | sending a number, string or boolean as the input declares |
| `prompt_no_outputs` / `prompt_outputs_failed_validation` | no output node, or every output's branch failed | reading the per-node errors; the top-level message alone is generic |

ComfyUI accepts a graph when **any** output passes, and drops the outputs
that fail, so a run can succeed with less than you asked for.

The relay reports those dropped outputs as warnings. *(needs the comfyrelay sidecar)*

## 3. While running: execution errors

A node can still fail at run time: out of memory, a corrupt model file, a
custom node's own exception. ComfyUI records it in the prompt's `/history`
entry.

The relay's `job_status` then reports `failed` with
`workflow_execution_failed`, naming the node id and class, the exception type
and message, and the last lines of the traceback. *(needs the comfyrelay sidecar)*
The relay's `workflow_interrupted` means something other than the relay
stopped the run (a person, or another client). *(needs the comfyrelay sidecar)*

## Reading errors well

- **Trust the per-node errors over the summary.** "Prompt outputs failed
  validation" says only that something failed; `node_errors` says what.
- **Fix one node at a time and resubmit.** ComfyUI reports every failing node
  at once, but one bad link often causes errors further down the graph.
- **Check against the instance, not the docs.** An input the docs mention may
  not exist on an older ComfyUI. `/object_info/<class>` shows what this one
  accepts. So does the relay's `node_describe`. *(needs the comfyrelay sidecar)*

ComfyUI's own description of the execution flow is on docs.comfy.org under
*Development → Server* (<https://docs.comfy.org/development/comfyui-server/comms_overview>).
