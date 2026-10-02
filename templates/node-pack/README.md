# Node-Pack Template

Files to copy (all but this README) into the root of a ComfyUI custom node pack's
own repository, to develop the pack against the `core` image. The guide is
[Developing Custom Nodes](../../docs/user-guides/developing-nodes.md).

| File | What it is |
|------|------------|
| `docker-compose.yml` | Runs `core` (CPU by default), with this repository mounted as the pack at `/app/custom_nodes/<PACK_NAME>`, everything else on named volumes, and ComfyUI published on `127.0.0.1` only |
| `docker-compose.gpu.yml` | The NVIDIA variant, used through `COMPOSE_FILE` in `.env` |
| `.env.example` | Copy it to `.env` and set `PACK_NAME`. Keep `.env` out of git |
| `dev-check.sh` | The loop: restarts ComfyUI (Manager's reboot, or `docker compose restart` without Manager), waits for it, and reports the pack's node classes, load errors and JavaScript, and optionally a workflow run. Needs bash, `curl` and `jq` |

```bash
cp .env.example .env      # set PACK_NAME
docker compose up -d
./dev-check.sh            # after each change to the pack's Python
```

This directory is a template, not a deployment: `PACK_NAME` is unset until a
`.env` sets it, and `./` is meant to be the pack. `tests/node-pack/run.sh` is its
test, run by CI's `node-pack` job.
