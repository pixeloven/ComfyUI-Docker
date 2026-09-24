# mcp — an MCP server for ComfyUI

A packaging of upstream [joenorton/comfyui-mcp-server](https://github.com/joenorton/comfyui-mcp-server),
pinned by `MCP_VERSION` in `docker-bake.hcl`. This repo writes none of the
server; it builds, pins and publishes it.

Standalone on `python:3.12-slim`: it does **not** depend on the ComfyUI runtime
images, and talks to ComfyUI over HTTP.

| | |
|---|---|
| Image | `ghcr.io/pixeloven/comfyui/mcp` |
| Port | `9000` |
| `COMFYUI_URL` | where ComfyUI is reachable (default `http://localhost:8188`) |
| User | non-root `comfy`, UID/GID `1000` by default (`APP_UID` / `APP_GID` build args) |

```sh
docker buildx bake mcp --load
docker run --rm -p 9000:9000 -e COMFYUI_URL=http://comfyui:8188 ghcr.io/pixeloven/comfyui/mcp:latest
```

## The one patch

Upstream constructs `FastMCP(..., port=9000)` and takes the host from the
constructor's default, `127.0.0.1`, which no environment variable can override.
Bound to loopback inside a container, the server is unreachable. The Dockerfile
`sed`s `host="0.0.0.0"` into that call. If an upstream bump changes the line, the
`sed` matches nothing and fails silently — check the port answers after bumping
`MCP_VERSION`.
