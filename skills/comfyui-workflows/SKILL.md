---
name: comfyui-workflows
description: Build, run and debug ComfyUI workflows as an agent — UI vs API JSON, adding models and nodes through a manifest change instead of installing, reading validation errors, and the comfyrelay sidecar's limits.
---

# Working with ComfyUI workflows

Short guides for an agent that drives a ComfyUI instance, especially one this
repository's images run. Each topic is its own file; read the one the task
needs. The comfyrelay MCP sidecar serves the same files through its
`docs_guide` tool, and `docs_search` searches them together with
[docs.comfy.org](https://docs.comfy.org).

## Topics

- [workflow-formats](references/workflow-formats.md): the editor's UI JSON
  against the API JSON that `/prompt` takes, and converting between them.
- [models-and-nodes](references/models-and-nodes.md): what to do when a
  workflow needs a model or node pack the instance lacks. Propose a manifest
  change; never install.
- [errors-and-validation](references/errors-and-validation.md): which check
  catches what, and how to read ComfyUI's per-node errors.
- [relay-limits](references/relay-limits.md): the comfyrelay sidecar's
  profiles, refusals, jobs and re-attaching. Needs the comfyrelay sidecar.
- [comfy-manifest](../comfy-manifest/SKILL.md): authoring `comfy.yaml` and
  generating its locks.

## Ground rules

- **Look things up; don't recall them.** Node inputs, defaults and allowed
  values change between ComfyUI versions. Ask the running instance
  (`/object_info`, or the relay's `node_describe`) rather than memory or a
  web page.
- **docs.comfy.org describes the latest ComfyUI.** The instance you drive may
  be older. Where the site and the instance disagree, the instance wins.
- **Change the deployment, not the instance.** Models and node packs come from
  the deployment's manifest and lock, reviewed by a human. An agent proposes
  that change; it doesn't install anything.
