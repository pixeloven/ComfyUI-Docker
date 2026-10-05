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

Converting by hand is possible but easy to get wrong. These are the rules the
editor's own export follows, checked against frontend 1.52.7; a hand
conversion has to follow them too.

- **`widgets_values` is positional, in `input_order`.** Pair its entries with
  the input names that `/object_info/<class>` lists under `input_order`
  (required, then optional). Inputs that only accept a link, such as an IMAGE
  or MODEL socket, take no position in the list, so skip them when counting.
- **When a widget input is linked, the link wins.** Its entry in
  `widgets_values` usually stays, but the API graph gets
  `["<source node id>", <output index>]`, found through the `links` array,
  instead of the stored value.
- **Some entries aren't inputs, so leave them out.**
  - A seed-like input with a "control after generate" setting is followed by
    one extra entry (`"fixed"`, `"randomize"` and so on). That setting belongs
    to the editor.
  - LoadImage's second entry (usually `"image"`) belongs to its upload button.
    The editor never sends that widget; only the file name is an input.
- **A dynamic combo expands into dotted names.** Its entry is the selected
  option, followed by the inputs that option adds. In the API graph the
  selector keeps its own name, and each added input is named
  `<selector>.<input>`, for example `resize_type.width`.
- **A list value is wrapped.** An input whose value is a JSON array is written
  as `{"__value__": [...]}`, so that ComfyUI doesn't take it for a link.
  ComfyUI unwraps it before the node runs.
- **Dynamic prompts are resolved on export.** In a text widget, the editor
  replaces each `{a|b|c}` group with one of its options, picked at random,
  and stores the result in `widgets_values` too. A hand conversion that
  copies the text with its braces sends a different prompt from the one the
  editor would.
- **Subgraphs are flattened.** Each node inside a subgraph instance (its
  definition is in `definitions.subgraphs`) moves to the top level, with the
  id `<instance id>:<inner id>`, for example `"12:3"`. Nesting adds a level
  per subgraph: `"12:3:7"` is node 7 inside instance 3, inside instance 12.
  Links that crossed the subgraph's edge are joined to the nodes outside.
- **Frontend-only nodes are dropped.** `Note`, `MarkdownNote`, `Reroute` and
  `PrimitiveNode` never reach `/prompt`. A link through a reroute goes
  straight from its source, and a primitive's value is written into each
  input it feeds.
- **Muted and bypassed nodes are skipped.** A muted node (`mode` 2) is left
  out, and so is every input linked from it: the node that read it gets no
  value for that input at all, not its stored widget value. A bypassed node
  (`mode` 4) is left out as well, and the nodes that read from it are wired to
  what fed it instead, matching by type.
- **A socketless widget must be there, with any value.** ImageCompare's
  `compare_view` has no socket and the node ignores its value, but the input
  is required, so the API graph must include it. Validation passes whatever
  it holds: the editor sends `{"__value__": ["", ""]}`, and `null` passes
  too.

When a graph is small it's often quicker to build the API form directly from
the node definitions (`/object_info/<class>`): pick the classes, fill every
required input, and wire outputs by index. The relay's `node_describe` gives
each definition with its inputs named as a graph must name them. *(needs the comfyrelay sidecar)*

## The relay's tools and the two formats

*Needs the comfyrelay sidecar.*

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
  `images.image0`).
- `node_describe` lists those inputs by the names a graph must use. *(needs the comfyrelay sidecar)*
