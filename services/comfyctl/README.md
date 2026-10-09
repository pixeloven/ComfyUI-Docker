# comfyctl

One command for ComfyUI-Docker's tooling. Each tool is a **group**, mounted from
its own Typer app rather than reimplemented, so a group behaves exactly like the
code behind it:

| Group | Verbs | Code |
|---|---|---|
| `comfyctl fetch` | `build`, `resolve`, `fetch`, `check`, `facts` | `comfyctl/fetch/`, in this package ([FETCH.md](FETCH.md)): manifest, lock and verified model downloads |
| `comfyctl relay` | `serve`, `probe`, `docs` | [`comfyrelay`](../comfyrelay/README.md): the MCP sidecar. It ships in the `mcp` and `mcp-convert` images, not in the wheel |

`comfyctl fetch` replaced the `comfyfetch` command in 4.0.0, with the same verbs,
flags, output and exit codes. Its code was the separate `comfyfetch` package
(`services/fetch/`) until 6.0.0 moved it into this one. More groups join as they
are built.

`comfyctl relay` exists only where comfyrelay is installed: in this workspace and in
the `mcp` and `mcp-convert` images. comfyctl doesn't depend on comfyrelay, and the
wheel and the `comfyctl` image don't include it, so there comfyctl has no `relay`
group in `--help`. There, `comfyctl
relay …` says it isn't available in this build, and exits 2.

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
and exit code as its own app (`comfyctl.fetch.cli`).

## Install

**Never install `comfyctl` from a package index.** It isn't registered on PyPI,
so anyone could publish a package under that name, and an index install would
run it. Install it from this repository: from a git tag, or as the release
wheel. Since 6.0.0 it is one package, with no first-party dependency.

Straight from git, pinned to a release tag:

```sh
uvx --from 'git+https://github.com/pixeloven/ComfyUI-Docker@v6.0.0#subdirectory=services/comfyctl' comfyctl --help
```

From a release, as one wheel (check it against the release's `SHA256SUMS`):

```sh
v=6.0.0
uv tool install "https://github.com/pixeloven/ComfyUI-Docker/releases/download/v${v}/comfyctl-${v}-py3-none-any.whl"
```

Up to 5.x a release shipped two wheels, installed together with
`--with <comfyfetch wheel url>`. From 6.0.0 there is no comfyfetch wheel.

Or run the `comfyctl` image, `ghcr.io/pixeloven/comfyui/comfyctl`, whose
entrypoint is `comfyctl`: `<image> fetch fetch /lock.yaml /app --apply`. See
[FETCH.md](FETCH.md).

## Developing

`services/` is a uv workspace (`services/pyproject.toml`), with this package and
`comfyrelay` as members and one `services/uv.lock`:

```sh
cd services
uv run --locked pytest -q         # every member's tests; add -m "not network" offline
uv run --locked comfyctl fetch check ../comfy.yaml ../comfy-lock.yaml
```

A new group is a package in the workspace, which adds its Typer app here with
`app.add_typer(<its app>, name="<group>")`, and follows the conventions above.
