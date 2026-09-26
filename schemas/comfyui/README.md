# ComfyUI node schema snapshot

`object_info.json` is ComfyUI's `GET /object_info` response for the ComfyUI version
pinned in `docker-bake.hcl`, so a pin bump shows up as a reviewable schema diff.

- **Built-in nodes of the CPU image only.** It is dumped from `core-cpu`, with no
  custom nodes (those live on the `/app/custom_nodes` volume) and no models. A node
  that needs an accelerator, or a dependency only `complete` installs, may be
  missing or described differently on another image.
- **The current pin only.** Git history holds the snapshots for earlier pins.
- **Keys sorted**, so diffs stay readable. The header fields `comfyui_version` (the
  image's `org.opencontainers.image.version` label) and `generated_from` sit beside
  the `object_info` body.

CI's `test-bake-targets` job fails when `comfyui_version` differs from the bake pin.
To regenerate the snapshot after a bump, build `core-cpu` and run the smoke test with
`--snapshot`:

```sh
make core-cpu
tests/smoke/run.sh --snapshot ghcr.io/pixeloven/comfyui/core:cpu-latest   # add --network host without a docker0 bridge
```
