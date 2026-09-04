# Versioning

Everything published here is semver'd, and **everything shares one version**. A
version is how a consumer says what they depend on and how we say what changed;
a commit-sha tag says neither.

## One release line

A `v1.2.3` tag publishes everything this repo produces, from one commit, in one
GitHub Release:

| artifact | where | how a consumer pins it |
|---|---|---|
| `complete` / `core` / `runtime` images | GHCR | `@sha256:…`, reads the semver tag |
| `mcp` image | GHCR | `@sha256:…` |
| `comfyfetch` image | GHCR | `@sha256:…` |
| `comfyfetch` **wheel** | release asset | URL + the published `SHA256SUMS` |
| skills plugin | the git tag | `@v1.2.3` |

The version lives in `VERSION`. `services/fetch/pyproject.toml` and
`.claude-plugin/plugin.json` must state the same number — checked on **every
push**, not at release time, because drift found on the tag is drift found too
late.

### Why not a line per component

There were two lines until 1.0.0: `v*` for the images, `comfyfetch/v*` for the
CLI. The reasoning was that the fetch tooling changes far more often than the
images, so a consumer pinning one shouldn't have to re-evaluate the other.

That reasoning was about *us*. What a consumer actually saw was a releases page
where neither entry described the repo, and where GitHub labels whichever
shipped last as "Latest" — so `comfyfetch 0.2.0` appeared to supersede
`ComfyUI images 0.1.0`. They were unrelated axes with colliding numbers.

The cost of consolidating is that `comfyfetch`'s version no longer means "what
changed in the CLI". The changelog means that. In exchange there is one number
to reason about, and one page that describes the whole repo.

## `version` is not `appVersion`

The image tags already carried `cuda-v0.34.0` — that is **`COMFYUI_VERSION`,
what is inside**. It is not a version of our packaging, and treating it as one
is a trap: change a Dockerfile without changing ComfyUI and `cuda-v0.34.0` is
overwritten with different bytes.

So both are published:

```
complete:cuda-v0.34.0   the ComfyUI release inside   (moves)
complete:cuda-1.2.3     our packaging of it          (cut once)
```

`COMFYUI_VERSION` is **pinned in `docker-bake.hcl`** and bumping it is a
deliberate commit. It used to be resolved from upstream at build time, which
made a release non-reproducible — the same tag rebuilt tomorrow baked a
different ComfyUI. Tracking upstream is the weekly rebuild's job.

## The tag does not define the version

The version lives in a file; the tag selects it. **CI refuses a tag that
disagrees**, because otherwise `v1.2.0` could ship `1.1.0` bytes and nothing
downstream could tell:

```
tag v1.2.0 does not match VERSION (1.1.0)
```

Prereleases are refused outright. `v1.2.3-rc1` matches the trigger glob but no
publish path, so it used to reach the build with an empty version and quietly
overwrite the stable tags.

## Pin by digest anyway

A tag can move; a digest cannot. Semver tags exist to say whether a digest
change was a **patch or a break** — which a commit-sha cannot express. Pin
`@sha256:…` and read the semver tag to decide whether to move. Every release
publishes `IMAGE-DIGESTS.txt` so the digests are readable without the registry.

Releases here are **not** immutable: that is a deliberate choice, so a release
can be corrected when there is a good reason. CI still refuses to publish over
an existing release, so the correction has to be deliberate rather than
accidental.

## What counts as major

A break in the **lock or manifest format**. Consumers pin those formats, so a
format change is not a patch however small the diff looks.

## Releasing

```sh
echo 1.2.3 > VERSION
# match it in services/fetch/pyproject.toml and .claude-plugin/plugin.json
# add a dated `## 1.2.3 — YYYY-MM-DD` section to CHANGELOG.md
git commit -am "release 1.2.3"
git tag v1.2.3 && git push --tags
```

A release rebuilds every image rather than reusing digests. It is ~60 minutes
and it happens rarely; the alternative is a release whose images came from a
different commit than its wheel.
