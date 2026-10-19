# Saved workflows: editing the file the user has open

The workflows a person saves in ComfyUI's editor are files in the user's
directory, `user/default/workflows/`, and the editor's workflows sidebar lists
and opens them from there. Editing one of them, rather than building a new
graph, hands the person back something they can open, inspect and run.

## Where they are and how the editor reads them

- **ComfyUI serves them through its userdata API.** `GET
  /api/userdata?dir=workflows&recurse=true&full_info=true` lists them, and
  `GET` or `POST /api/userdata/workflows%2F<name>` reads or writes one. The
  path is one URL segment, with its `/` encoded as `%2F`. A `POST` replaces
  an existing file unless the query says `overwrite=false`, which gets HTTP
  409 instead.
- **The sidebar opens the UI format only.** It reads a file's `nodes` and
  `links`. An API-format file (`{"<id>": {"class_type": ...}}`) opens as an
  empty canvas, with no error shown, and saving that tab writes the empty
  graph over it. (Checked on frontend 1.53.6.) By the frontend's source,
  dropping an API-format file on the canvas does load it, but that is
  another path, not the sidebar's.
- **The editor writes compact JSON**, `JSON.stringify` with no spaces. A file
  written the same way reads back the same bytes.
- **An open tab keeps its own copy.** Changing the file doesn't change a tab
  that already shows it. Closing that tab and opening the file again from the
  sidebar, or reloading the page, shows the new file. (Checked on frontend
  1.53.6, with a tab that had no unsaved changes.) Tell the person to do that,
  and to avoid saving the stale tab first: saving it writes their copy back
  over yours. By the frontend's source, unsaved edits kept for a tab are
  dropped when the file on disk is newer.

## Editing one

1. Read the file and keep it in the UI format.
2. Change only what the task asks. A node's settings are its
   `widgets_values`, in the order the editor draws the widgets: find the
   position from the node's inputs in `/object_info/<class>` (`input_order`),
   as the `workflow-formats` topic explains. Leave `links`, ids, positions and
   everything else as they are, so the person sees the graph they left.
3. Write it back under the same name, in the same format. Don't save an API
   export of it in the library: the sidebar can't open that.
4. To run it, convert it to the API format first (the `workflow-formats`
   topic), and submit that to `/prompt`.

## With the relay

*Needs the comfyrelay sidecar.*

| Tool | Profile | Does |
|---|---|---|
| `workflow_list_saved` | `read` | Lists the saved workflows, newest first, with size and modification time (at most 200). |
| `workflow_get_saved` | `read` | Returns one by name, with its `format` (`ui`, `api` or `unknown`). |
| `workflow_save` | `run` | Writes one. UI format only. |

`workflow_validate` and `workflow_run` also take a saved workflow by name:
`workflow_run(saved="portrait.json")` reads the file through ComfyUI and runs
it, so the graph doesn't have to travel through your context again. Where the
relay converts (`server_info.capabilities.conversion`), a UI-format file is
converted first, as a UI graph passed inline is.

- **Names** are paths in the workflows folder, as `workflow_list_saved` gives
  them, ending in `.json`: `portrait.json`, or `portraits/old.json`. A leading
  `workflows/` is dropped. A name with `..`, a leading `/`, a backslash, a
  `%`, a control character, an empty folder or a part starting with a dot is
  refused with `invalid_workflow_name`, and nothing reaches ComfyUI. An
  unknown name gets `unknown_saved_workflow`, with close names.
- **Replacing needs `overwrite: true`.** Without it, saving onto a name that
  exists is refused with `workflow_exists`, and the file is left as it was.
  ComfyUI makes that check as it writes, so nothing can slip in between.
- **API format is refused** with `api_format_not_saved`, because the sidebar
  would open it as an empty canvas. Something that is neither format gets
  `invalid_workflow`. Nothing is written in either case.
- **The bytes are kept when nothing changed.** `workflow_save` writes JSON the
  way the editor does, so a workflow read and saved unchanged is the same
  file. With `overwrite: true`, a save whose content the file already holds
  isn't written at all (`written: false`), even if another tool formatted it.
- **The graph isn't checked when it's saved.** Work in progress saves as it
  is. `workflow_validate(saved=name)` checks it.
- **Caps.** A file over 2 MiB isn't read or written
  (`saved_workflow_too_large`). `workflow_get_saved` returns at most 80,000
  characters of JSON (`workflow_too_large`), but `workflow_run(saved=)` runs a
  larger one.

A typical edit: `workflow_get_saved`, change the values, `workflow_save` with
`overwrite: true`, `workflow_run(saved=...)`, then `job_status` to wait for
it. Start with `workflow_list_saved` if you don't know the name.
