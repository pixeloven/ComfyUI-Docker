---
name: comfyui-docker-protected-seams
description: Registry of ComfyUI-Docker changes that need owner sign-off — release/version and publish paths, the COMFYUI_VERSION pin, the manifest and lock format, the runtime contract (env vars, volumes, UID, tags), secrets and credentials, supply-chain pins, and the published skill. Load when reviewing or authoring a diff that touches VERSION, workflows, docker-bake.hcl tags or pins, schemas, entrypoint, examples, or skills/.
---

Each seam is a pattern that consumers pin, or that publishes without a human in
the loop. When a diff touches one, **flag it for the owner**. Don't block. Name the
seam in the PR description with what changed and why. The generic mechanics are
in the foundation's `seam-detection` and `seam-alert-routing` skills; this
registry is what they check against.

## Seams

### 1. Release line and publish paths

- **Pattern:** `VERSION`; the version in `services/fetch/pyproject.toml`,
  `services/comfyctl/pyproject.toml` (and its `comfyfetch==` pin),
  `services/comfyrelay/pyproject.toml`, `.claude-plugin/plugin.json`,
  `package.json`, and the `comfyfetch`, `comfyctl` and `comfyrelay` entries in
  `services/uv.lock`; the `context` and `release` jobs in `ci.yml` (including
  which workspace packages the release builds wheels for); `IMAGE_LABEL`,
  `PUBLISH_LATEST`, `IMAGE_VERSION`, `FETCH_VERSION` and every `tags = [...]` in
  `docker-bake.hcl`, and which targets `group "all"` holds; comfyctl's
  dependencies; anything in `nightly.yml` that sets tags.
- **Risk:** a tag starts meaning two things. The nightly moving `*-latest` hands every
  consumer an unreviewed upstream commit. A hand-made Release makes the release job
  fail after images publish. The `context` job fails any push where the
  version files disagree; a change that drops a file from that check lets a
  partial bump ship.
- **Response:** flag it. Check against `VERSIONING.md`: one version line, three
  publishing paths, CI creates the Release.

### 2. The ComfyUI pin

- **Pattern:** `COMFYUI_VERSION` in `docker-bake.hcl`.
- **Risk:** it changes what every release image contains. A bump that lands with an
  upstream migration can rebuild `comfyui.db`, as the 0.34 to 0.37 bump did.
- **Response:** flag it. The PR states the old and new versions and what upstream
  changed that consumers will see, and adds a `CHANGELOG.md` section.

### 3. Manifest and lock format

- **Pattern:** `services/fetch/comfyfetch/schemas/*.json`, `schema.py`, `lockfile.py`,
  any change to which keys `comfy.yaml` or a lock accepts, and CLI verbs or flags
  (`comfyctl`, and the comfyfetch app it mounts as `comfyctl fetch`).
- **Risk:** consumers pin these formats. `VERSIONING.md` says a format break is
  **major**, however small the diff.
- **Response:** flag it and classify it as major or not. Update `skills/comfy-manifest/SKILL.md`
  in the same change, because no test compares it with the CLI.

### 4. Runtime contract

- **Pattern:** env var names and defaults (`PUID`, `PGID`, `COMFY_*`, `CLI_ARGS`),
  volume paths under `/app`, the port, `entrypoint.sh` user, chown and gosu logic,
  the `mcp` image's promises (`COMFYUI_MCP_HTTP_TOKEN` required and at least 32
  characters, `MCP_PORT` 9000, the `/mcp` path, `COMFYUI_URL`, the tool names and
  which profile holds each, `COMFYUI_MCP_PROFILES` and its default,
  `COMFYUI_MCP_MAX_LARGE_REQUESTS` and its default, `USER 1000:1000` and any UID,
  `SIGTERM` handling; `docs/user-guides/runtime-contract.md` → *The `mcp` Image*),
  the `mcp-convert` image's (all of those, plus `COMFYUI_MCP_CONVERT` on by default,
  `COMFYUI_MCP_CONVERT_PAGES` and its default, a writable `/tmp`, and which formats
  `template_get`, `workflow_validate` and `workflow_run` take; *The `mcp-convert` Image*),
  the fetch image's `ENTRYPOINT` in `dockerfile.comfy.fetch` (`comfyctl fetch fetch`:
  Jobs and Compose append `/lock.yaml /app --apply` to it, and overrides name the
  binary), the permission steps in `dockerfile.comfy.core`, the volume mounts in
  `examples/*/docker-compose.yml`, and removing a bake target, image, or example.
- **Risk:** a deployment that worked breaks on `docker compose pull`, or only under
  a UID nobody tested. That includes Kubernetes `runAsUser` deployments, which
  this repo cannot see.
- **Response:** flag it. Keep existing volume mounts working. A break is a **major**
  version (`VERSIONING.md` → *What counts as major*); the owner confirms the
  classification.

### 5. Secrets and credentials

- **Pattern:** `secrets.*` in workflows (today `HF_TOKEN`, used by the fetch tests,
  and `GITHUB_TOKEN`), the `auth:` map in `comfy.yaml` (values must be `${ENV_VAR}`),
  `services/fetch/comfyfetch/auth.py`, and any `ENV`, `ARG` or file in an image
  that could carry a token.
- **Risk:** a credential baked into a public image or committed to a public repo.
- **Response:** flag it. Credentials are resolved from the environment by host, and
  never from a lock or an image.

### 6. Supply-chain pins

- **Pattern:** `SAGEATTENTION_RELEASE_URL` and each `SAGEATTENTION_WHEEL_SHA256`,
  the `sam2` commit in `extra-requirements.txt`, the base images in
  `services/*/dockerfile.*` and `services/comfy/*/dockerfile.*` (including the `mcp`
  image's `ghcr.io/astral-sh/uv` build stage), the `mcp-convert` image's exact
  `playwright==` pin (comfyrelay's `convert` extra), its `CHROMIUM_REVISION` and
  `CHROMIUM_TREE_SHA256` checks, and the package names its `runtime-1` stage
  installs (names only: their versions come unpinned from the digest-pinned
  base's Debian sources, owner decision on #191; integrity is the base digest
  and the Chromium tree hash, freshness is rebuilding and moving Playwright about
  monthly, so flag a change that pins a version, drops the hash check, or lets
  the Playwright pin go stale), the `mcp` image's `tini` apt version
  and its builder step that strips the SDK's `mcp` CLI from the venv and fails the
  build if `mcp.cli` or `dotenv` can be imported, `COMFY_DOCS_SHA` in
  `docker-bake.hcl` (the Comfy-Org/docs commit the relay's docs index covers:
  GPL-3.0 content, pinned by full SHA and bumped by PR, #134; a bump must be a commit on
  Comfy-Org/docs `main`, because GitHub serves any SHA in the fork network; CI's
  `docs-pin` job checks it on every PR that touches `docker-bake.hcl`, and on every
  `v*` tag), comfyrelay's exact
  `mcp==` pin and `services/uv.lock`, which its image installs as written, and action
  versions in workflows.
- **Risk:** executing unreviewed third-party code, or a silent ABI or behavior change.
  An SDK minor has changed what a tool error looks like to the client
  (`services/comfyrelay/pyproject.toml`), and the image builds its docs index from a
  third-party repository at build time.
- **Response:** flag any change that removes a hash or moves a pin to a moving ref.
  A routine Dependabot action bump is expected.

### 7. The published skill surface

- **Pattern:** `skills/**`, `.claude-plugin/*.json`, and the `pi` key or `files` in
  `package.json`.
- **Risk:** it ships to every Claude Code, Codex and pi consumer on the next tag. A
  missing `"skills": "./skills"` or `pi.skills` key installs zero skills, silently,
  on that harness (`skills/README.md`).
- **Response:** flag it. Local agent skills belong in `.agents/skills/`, never here.

## Registry ownership

The repo owner (`@ductiletoaster`, from `.github/CODEOWNERS`) approves seam
crossings in PR review. A new seam gets added to this file by PR, with the
owner's approval.
