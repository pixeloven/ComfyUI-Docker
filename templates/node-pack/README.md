# Node-Pack Template

Files to copy (all but this README) into the root of a ComfyUI custom node pack's
own repository, to develop the pack against the `core` image. The guide is
[Developing Custom Nodes](../../docs/user-guides/developing-nodes.md).

| File | What it is |
|------|------------|
| `docker-compose.yml` | Runs `core` (CPU by default), with this repository mounted as the pack at `/app/custom_nodes/<PACK_NAME>`, everything else on named volumes, and ComfyUI published on `127.0.0.1` only |
| `docker-compose.gpu.yml` | The NVIDIA variant, used through `COMPOSE_FILE` in `.env` |
| `.env.example` | Copy it to `.env` and set `PACK_NAME`. Keep `.env` out of git |
| `dev-check.sh` | The loop: restarts ComfyUI (Manager's reboot, or `docker compose restart` without Manager unless `--no-docker-fallback`), waits for it, and reports the pack's node classes, load errors and JavaScript, and optionally a workflow run. Needs bash, `curl` and `jq` |

```bash
cp .env.example .env      # set PACK_NAME, and pin COMFY_IMAGE
docker compose up -d
./dev-check.sh            # after each change to the pack's Python
./dev-check.sh --workflow workflows/smoke.json   # keep API-format workflows in workflows/
```

**Pin the image.** The default, `core:cpu-latest`, moves with every merge to our
`main`. For reproducible results, set `COMFY_IMAGE` in `.env` to a release tag and
its digest (`core:cpu-X.Y.Z@sha256:<digest>`).

**Upgrading.** These files are copied, so nothing updates them. When you move to a
new release, diff your copies against `templates/node-pack/` in that release.

**What pack repos may rely on.** `PACK_NAME`, the mount path
`/app/custom_nodes/${PACK_NAME}`, the `COMFY_*` variables the compose file reads,
and `dev-check.sh`'s flags and exit codes (0 every check passed, 1 one failed, 2 a
usage error). A change to any of them is a versioned change of this repository.

This directory is a template, not a deployment: `PACK_NAME` is unset until a
`.env` sets it, and `./` is meant to be the pack. `tests/node-pack/run.sh` is its
test, run by CI against the published `core:cpu-latest` when only the template
changes, and against the pull request's own `core-cpu` build in `smoke-cpu`
whenever the image changes.
