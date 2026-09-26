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

- **One output flag:** `--output auto|plain|json` (`-o`) on every verb, such as
  `comfyctl fetch check … -o json`. Groups take no `-o` of their own, so
  `comfyctl fetch -o json check …` is an error. `auto`
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
verb (every leaf command) takes the output flag, and that `comfyctl fetch` gives the same stdout
and exit code as comfyfetch's own app.

## Install

**Never let an installer resolve `comfyfetch` from a package index.** Neither
`comfyctl` nor `comfyfetch` is registered on PyPI, so anyone could publish a
package under either name, and an index install would run it. `comfyctl`
depends on `comfyfetch==<same version>`, so every install below supplies
comfyfetch itself: from the same git commit, or as the named release wheel.

Straight from git, pinned to a release tag (uv resolves comfyfetch from the same
commit, through the workspace):

```sh
uvx --from 'git+https://github.com/pixeloven/ComfyUI-Docker@v4.0.0#subdirectory=services/comfyctl' comfyctl --help
```

Use uv for this line. `pip install git+…#subdirectory=services/comfyctl`
ignores the workspace and looks `comfyfetch` up on PyPI instead.

From a release, as two wheels, naming both. The `--with` wheel is what keeps
comfyfetch coming from the release:

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
uv run --locked pytest -q         # every member's tests; add -m "not network" offline
uv run --locked comfyctl fetch check ../comfy.yaml ../comfy-lock.yaml
```

A new group is a package in the workspace, which adds its Typer app here with
`app.add_typer(<its app>, name="<group>")`, and follows the conventions above.
