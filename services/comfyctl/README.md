# comfyctl

One command for ComfyUI-Docker's tooling. Each tool is a **group**, mounted from
its own package rather than reimplemented, so a group behaves exactly like the
library behind it:

| Group | Verbs | Package |
|---|---|---|
| `comfyctl fetch` | `build`, `resolve`, `fetch`, `check`, `facts` | [`comfyfetch`](../fetch/README.md): manifest, lock and verified model downloads |

`comfyctl fetch` replaced the `comfyfetch` command in 4.0.0, with the same verbs,
flags, output and exit codes. More groups join as they are built.

## Conventions every group follows

Automation and agents read these, so they are part of the interface. A group
that breaks one is a bug.

- **One output flag:** `--output auto|plain|json` (`-o`) on every command. `auto`
  colours at a terminal and goes plain when piped, which covers every CI job and
  every container. `json` gives stable keys.
- **stdout is the result, stderr is everything else.** `comfyctl fetch resolve … > lock.yaml`
  captures the lock and none of the progress, and `-o json | jq` always parses.
- **One exit-code scheme:**

  | exit | meaning |
  |---|---|
  | `0` | did what was asked |
  | `1` | a real failure: a source did not resolve, a hash did not match, a lock and its manifest disagree |
  | `2` | the request itself was wrong: a missing file, an unknown profile, incompatible flags |

`comfyctl --help` says the same. `tests/test_comfyctl.py` asserts that every
command takes the output flag, and that `comfyctl fetch` gives the same stdout
and exit code as comfyfetch's own app.

## Install

From a checkout, or straight from git:

```sh
uvx --from git+https://github.com/pixeloven/ComfyUI-Docker#subdirectory=services/comfyctl comfyctl --help
```

From a release, as two wheels. `comfyctl` pins `comfyfetch` to the same
version, and neither is on PyPI, so name both wheels. That way comfyfetch can
only come from the release:

```sh
v=4.0.0
uv tool install \
  "https://github.com/pixeloven/ComfyUI-Docker/releases/download/v${v}/comfyctl-${v}-py3-none-any.whl" \
  --with "https://github.com/pixeloven/ComfyUI-Docker/releases/download/v${v}/comfyfetch-${v}-py3-none-any.whl"
```

Or run the `fetch` image, whose entrypoint is `comfyctl fetch fetch`. See
[../fetch/README.md](../fetch/README.md).

## Developing

`services/` is a uv workspace (`services/pyproject.toml`), with this package and
`comfyfetch` as members and one `services/uv.lock`:

```sh
cd services
uv run pytest -q                  # every member's tests; add -m "not network" offline
uv run comfyctl fetch check ../comfy.yaml ../comfy-lock.yaml
```

A new group is a package in the workspace, which adds its Typer app here with
`app.add_typer(<its app>, name="<group>")`, and follows the conventions above.
