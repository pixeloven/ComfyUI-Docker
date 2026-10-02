`pack/` holds a ComfyUI custom node pack, written with ComfyUI's V3 node API, that doesn't work. It should provide two nodes in category `t7`:

- `T7Reverse`: one required STRING input named `text`, and one STRING output: the input reversed.
- `T7Show`: an output node with one required STRING input named `text`, which it displays in the UI as text.

Find out from ComfyUI what is wrong, fix the pack, and make the running ComfyUI load it without recreating its container. A workflow in which `T7Reverse` feeds `T7Show` must run and show the reversed text, and ComfyUI must log no error loading the pack. Fix what is broken and keep the V3 node API.
