---
name: comfyui-workflows
description: Build, run and debug ComfyUI workflows as an agent — UI vs API JSON, adding models and nodes through a manifest change instead of installing, reading validation errors, and the comfyrelay sidecar's limits.
---

# Working with ComfyUI workflows

Short guides for an agent that drives a ComfyUI instance, especially one this
repository's images run. Each topic is its own file; read the one the task
needs.

The comfyrelay MCP sidecar serves the same files through its `docs_guide`
tool, and `docs_search` searches them together with
[docs.comfy.org](https://docs.comfy.org). *(needs the comfyrelay sidecar)*

**The marker.** *(needs the comfyrelay sidecar)* ends each sentence that
relies on comfyrelay, the MCP server this repository runs beside ComfyUI, and a
section that relies on it opens with *Needs the comfyrelay sidecar.* Without
the relay, skip just those sentences and sections: the rest holds for any
ComfyUI, through its HTTP API and editor.

## Topics

- [workflow-formats](references/workflow-formats.md): the editor's UI JSON
  against the API JSON that `/prompt` takes, and converting between them.
- [models-and-nodes](references/models-and-nodes.md): what to do when a
  workflow needs a model or node pack the instance lacks. Propose a manifest
  change; never install.
- [errors-and-validation](references/errors-and-validation.md): which check
  catches what, and how to read ComfyUI's per-node errors.
- [relay-limits](references/relay-limits.md): the comfyrelay sidecar's
  profiles, refusals, jobs and re-attaching. The whole topic needs the sidecar.
- [comfy-manifest](../comfy-manifest/SKILL.md): authoring `comfy.yaml` and
  generating its locks.

## Ground rules

- **Look things up; don't recall them.** Node inputs, defaults and allowed
  values change between ComfyUI versions. Ask the running instance
  (`/object_info`) rather than memory or a web page. The relay's
  `node_describe` asks it for you. *(needs the comfyrelay sidecar)*
- **docs.comfy.org describes the latest ComfyUI.** The instance you drive may
  be older. Where the site and the instance disagree, the instance wins.
- **Change the deployment, not the instance.** Models and node packs come from
  the deployment's manifest and lock, reviewed by a human. An agent proposes
  that change; it doesn't install anything.
