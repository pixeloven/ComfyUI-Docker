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

CI's `snapshot-pin` job fails when `comfyui_version` differs from the bake pin, and
the release job needs it. The smoke test also fails when the image is the pinned
ComfyUI and a node class listed here is missing from it.

After a pin bump, commit the `object_info.json` from the `smoke-cpu` job's artifact,
or regenerate it locally from `core-cpu` built from the tree:

```sh
make smoke   # builds ghcr.io/pixeloven/comfyui/core:cpu-smoke; add SMOKE_NETWORK=host without a docker0 bridge
tests/smoke/run.sh --snapshot ghcr.io/pixeloven/comfyui/core:cpu-smoke   # --network host likewise
```
