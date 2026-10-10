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
| `mcp` image (comfyrelay) | GHCR | `@sha256:…` |
| `mcp-convert` image (comfyrelay with a headless Chromium) | GHCR | `@sha256:…` |
| `comfyctl` image (the CLI, including `comfyctl fetch`) | GHCR | `@sha256:…` |
| `comfyctl` **wheel** | a release asset | URL + the published `SHA256SUMS` |
| `comfyctl-X.Y.Z-requirements.txt` (the wheel and every dependency, hash-locked from `services/uv.lock`) | a release asset | `pip install --require-hashes -r`, attested like the wheel |
| skills plugin | the git tag | `@v1.2.3` |

The version lives in `VERSION`. `services/comfyctl/pyproject.toml`,
`services/comfyrelay/pyproject.toml`, `.claude-plugin/plugin.json`,
`package.json`, and the `comfyctl` and `comfyrelay` entries in
`services/uv.lock` must state the same number — checked on **every push**, not
at release time, because drift found on the tag is drift found too late.
comfyrelay ships as the `mcp` and `mcp-convert` images, not as a wheel, and they report
its version, so it moves with the others.

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

## Three publishing paths, and only three

A tag on our images answers one of three questions, and never two:

| Tag | Means | Written by |
|---|---|---|
| `complete:cuda-<sha8>` | a build of our main | push to `main` (also moves `cuda-latest`) |
| `complete:cuda-1.2.3` | our packaging, released | a `v1.2.3` tag |
| `complete:cuda-nightly` | upstream **master**, followed | the nightly (never moves `cuda-latest`) |

**What is inside an image is not a tag.** It used to be: every target also
published `cuda-v<COMFYUI_VERSION>`. That made an unreviewed cron the author of
the release-image line — it resolved upstream's latest release and published
`cuda-v0.36.0`, while a reviewed release published `cuda-2.0.0` containing
`v0.34.0`. Two identities for one artifact, disagreeing, and a consumer pinning
our version got an OLDER ComfyUI than one pinning `latest`.

The ComfyUI inside is now stated once, by `org.opencontainers.image.version`:

```sh
docker inspect --format '{{index .Config.Labels "org.opencontainers.image.version"}}' <image>
```

That is true for a commit as well as a release tag, which matters because the
nightly builds commits.

`COMFYUI_VERSION` is **pinned in `docker-bake.hcl`** and bumping it is a
deliberate commit. It used to be resolved from upstream at build time, which
made a release non-reproducible — the same tag rebuilt tomorrow baked a
different ComfyUI. Following upstream is the NIGHTLY's job, and it passes a
resolved commit rather than a moving ref, so any nightly can be rebuilt.

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

Anything that breaks a consumer who changes nothing but the version they pull:

- **The lock or manifest format.** Consumers pin those formats, so a format
  change is not a patch however small the diff looks.
- **[The runtime contract](docs/user-guides/runtime-contract.md).** An env var renamed, removed, or given a new meaning
  (`PUID`, `PGID`, `COMFY_*`, `CLI_ARGS`); a volume path under `/app`; the port;
  how the entrypoint handles the UID. A compose file or Kubernetes manifest that
  worked on `1.4` must still work on `1.5`, and this repo cannot see most of
  them.
- **A removed image, profile, or example.** Someone's `image:` line points at it.
- **A removed or renamed command, verb or flag.** `comfyfetch` becoming
  `comfyctl fetch` in 4.0.0 is the example: every script that typed the old
  name breaks.
- **An MCP tool, an argument of one, or information one gives, removed or
  narrowed.** Renaming or removing a tool of the `mcp` image (comfyrelay) is
  major, and so is moving a tool to a different capability profile
  (`COMFYUI_MCP_PROFILES`): a deployment that enabled only the old profile
  loses it. So is renaming or removing one of a tool's arguments, adding a
  required argument, narrowing what an argument accepts (its range or its
  allowed values), or changing an argument's default. Dropping information a
  tool returns is major unless the same information is still **returned by
  another tool of the same server, under the same capability profile**
  (`COMFYUI_MCP_PROFILES`). `template_search` hits summarising their
  runnability while `template_get`, also in `read`, keeps the full lists (#167)
  is the example. The JSON shape of a tool's output is deliberately not a
  contract, which makes it the one exception to the definition above: an agent
  reads the output, and a reshape that keeps the information is minor. A script that
  parses a tool's output should pin an image version.

Adding something optional is never major: a new env var, volume, profile,
image, tool, or optional tool argument is a minor.

## Releasing

Before tagging, the lead session runs agent tasks T1–T6 against comfyrelay and posts the scores on the release PR: see [`tests/agent-tasks/README.md`](tests/agent-tasks/README.md) → *Before each release*.

The bump goes through a release PR like any other change; only the tag is
pushed by hand, and only after that PR merges:

```sh
git switch -c chore/release-1.2.3 origin/main
echo 1.2.3 > VERSION
# match it in services/comfyctl/pyproject.toml, services/comfyrelay/pyproject.toml,
# .claude-plugin/plugin.json and package.json
(cd services && uv lock)   # after the pyproject.toml edits: uv.lock copies the versions
# turn CHANGELOG.md's `## Unreleased` into a dated `## 1.2.3 — YYYY-MM-DD` section
git add VERSION CHANGELOG.md services/comfyctl/pyproject.toml services/comfyrelay/pyproject.toml \
  services/uv.lock .claude-plugin/plugin.json package.json
git commit -m "chore(release): prepare 1.2.3"
git push -u origin chore/release-1.2.3
gh pr create --fill        # review, CI green, merge

# After the PR merges: tag its merge commit on main, and push that one tag.
sha="$(gh pr view chore/release-1.2.3 --json mergeCommit --jq .mergeCommit.oid)"
git fetch origin && git tag v1.2.3 "${sha}"
git push origin v1.2.3     # never --tags: that pushes every local tag, and each v* tag publishes
```

**Check a new image's GHCR package is public, once.** A package GHCR creates
on CI's first push can start private. After the first `main` push that
publishes a new image (`mcp-convert` is the latest), check its package's
visibility on GitHub, and make it public before the release that announces it;
otherwise every consumer's pull fails with `unauthorized`.

A release rebuilds every image rather than reusing digests. It is ~60 minutes
and it happens rarely; the alternative is a release whose images came from a
different commit than its wheel.

**Push the tag. Never create the GitHub Release by hand.** The tag is the
trigger; CI does the rest — it checks every version file agrees with the tag,
builds every image from that one commit, builds and *attests* the wheel and
its hash-locked requirements file, and creates the Release with
`comfyctl-<ver>-py3-none-any.whl`, `comfyctl-<ver>-requirements.txt`,
`SHA256SUMS` and `IMAGE-DIGESTS.txt` attached. Up to 5.x it also attached a
`comfyfetch-<ver>-py3-none-any.whl`.

`gh release create` looks equivalent and is not. CI refuses to write into a
Release that already exists — *"releases are immutable"* — so creating one by
hand makes the release job **fail after the images have already published**.
The version is then correct everywhere and the Release page is empty. That is
what happened to v2.1.0, v2.2.0 and v2.3.0; compare them with v2.0.0, which has
all three assets.

The assets cannot be backfilled faithfully. The wheel carries a build
provenance attestation tied to the workflow run (`attest-build-provenance`,
verified in the same job), and a hand-uploaded wheel would look official while
carrying none. A missing asset is honest; an unattested one is not.
