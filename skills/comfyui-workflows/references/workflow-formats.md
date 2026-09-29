# Workflow formats: UI JSON and API JSON

ComfyUI has two JSON shapes for one graph, and most tooling takes only one of
them. Saving a workflow in the editor gives the **UI format**; running one
through `POST /prompt` takes the **API format**. Mixing them up is the most
common reason a workflow "doesn't load" or is rejected before it runs.

## Telling them apart

| | UI format (editor save file) | API format (what `/prompt` runs) |
|---|---|---|
| Top level | an object with a `nodes` array, a `links` array, and fields such as `version`, `groups`, `extra`, `definitions` | an object keyed by node id: `{"3": {...}, "4": {...}}` |
| A node | `id`, `type` (the class), `pos`, `size`, `mode`, `inputs` and `outputs` slots, and `widgets_values` | `class_type` and `inputs`, plus an optional `_meta.title` |
| An input value | a position in `widgets_values`, in the order the editor draws the widgets | a named key in `inputs`, holding the value itself |
| A connection | an entry in `links` that the two nodes' slots refer to by link id | an input whose value is `["<source node id>", <output index>]` |
| Editor-only nodes | present: `Note`, `MarkdownNote`, `Reroute`, `PrimitiveNode` | absent: the editor drops or resolves them on export |
| Muted and bypassed nodes | present, with `mode` 2 (muted) or 4 (bypassed) | absent: a muted node is left out, and a bypassed one is wired through |

A quick test: a top-level `nodes` list means UI format. Values that are all
objects with a `class_type` mean API format. The formal schema of the UI format
is on docs.comfy.org under *Specifications → Workflow JSON*
(<https://docs.comfy.org/specs/workflow_json>).

## Converting UI to API

The reliable conversion is ComfyUI's own: open the workflow in the editor and
export it in API format ("Export (API)" in the workflow menu). The editor knows
each node's widget order, resolves primitives and reroutes, and flattens
subgraphs, so its export is what `/prompt` expects.

Converting by hand is possible but easy to get wrong:

- `widgets_values` is positional. Map it to input names with the node's
  definition (`/object_info/<class>`, or `node_describe`), in the order the
  inputs are declared.
- A seed-like input with a "control after generate" widget has an extra value
  after it in `widgets_values` (`"fixed"`, `"randomize"` and so on). That value
  isn't an input, so skip it.
- An input fed by a link has no widget value to copy. Follow the link instead:
  `links` entries hold the source node and its output slot.
- Nodes inside a subgraph (`definitions.subgraphs`) must be brought up to the
  top level, with ids that stay unique.

When a graph is small it's often quicker to build the API form directly from
`node_describe`: pick the classes, fill every required input, and wire outputs
by index.

## The relay's tools and the two formats

With the comfyrelay sidecar:

- `template_get` returns a template as the editor loads it: **UI format**.
  Use it to learn which nodes and models a template needs, not to run it.
- `workflow_validate` and `workflow_run` take **API format** only. Given a UI
  save file, `workflow_validate` reports an `invalid_workflow` problem that says
  to export the API format, and `workflow_run` refuses it (`workflow_invalid`).
- `workflow_run` takes the graph alone, not a whole `/prompt` body. It chooses
  the prompt id itself.

## API format essentials

```json
{
  "1": {"class_type": "LoadImage", "inputs": {"image": "photo.png"}},
  "2": {"class_type": "ImageInvert", "inputs": {"image": ["1", 0]}},
  "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": "inverted"}}
}
```

- Node ids are strings, and a link names its source id as a string too.
- The output index counts from 0 in the order `/object_info` lists the node's
  outputs. LoadImage's outputs are IMAGE then MASK, so `["1", 1]` is the mask.
- A graph needs at least one output node (such as SaveImage or PreviewImage).
  ComfyUI runs only the nodes an output depends on.
- Inputs added by a dynamic input use dotted names (`resize_type.width`,
  `images.image0`). `node_describe` lists them as a graph must name them.
