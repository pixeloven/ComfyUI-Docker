# Versioning

Everything published here is semver'd. A version is how a consumer says what it
depends on and how we say what changed; a commit-sha tag says neither.

## Two release lines, because two lifecycles

| tag | releases | version lives in |
|---|---|---|
| `v1.2.3` | the ComfyUI images — `complete`, `core`, `runtime`, `mcp` | `VERSION` |
| `comfyfetch/v1.2.3` | the `comfyfetch` CLI and its image | `services/fetch/pyproject.toml` |

They move independently on purpose: the fetch tooling changes far more often
than the ComfyUI images, and a consumer pinning one should not be forced to
re-evaluate the other.

## `version` is not `appVersion`

The image tags already carried `cuda-v0.33.1` — that is **`COMFYUI_VERSION`,
what is inside**. It is not a version of our packaging, and treating it as one
is a trap: change a Dockerfile without changing ComfyUI and `cuda-v0.33.1` is
overwritten with different bytes.

So both are published:

```
complete:cuda-v0.33.1   the ComfyUI release inside   (moves)
complete:cuda-1.2.3     our packaging of it          (immutable)
```

## The tag does not define the version

The version lives in a file; the tag selects it. **CI refuses a tag that
disagrees**, because otherwise `v0.2.0` could ship `0.1.0` bytes and nothing
downstream could tell:

```
tag v0.2.0 does not match the VERSION file (0.1.0)
```

## Pin by digest anyway

A tag can move; a digest cannot. Semver tags exist to say whether a digest
change was a **patch or a break** — which a commit-sha cannot express. Pin
`@sha256:…` and read the semver tag to decide whether to move.

## What counts as major

A break in the **lock or manifest format**. Consumers pin those formats, so a
format change is not a patch however small the diff looks.

## Releasing

```sh
echo 0.2.0 > VERSION && git commit -am "release 0.2.0"
git tag v0.2.0 && git push --tags
```
