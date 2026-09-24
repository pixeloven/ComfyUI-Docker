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
  `.claude-plugin/plugin.json`, `package.json` and the `comfyfetch` entry in
  `services/fetch/uv.lock`; the `context` and `release` jobs in `ci.yml`;
  `IMAGE_LABEL`, `PUBLISH_LATEST`, `IMAGE_VERSION`, `FETCH_VERSION` and every
  `tags = [...]` in `docker-bake.hcl`; anything in `nightly.yml` that sets tags.
- **Risk:** a tag starts meaning two things. The nightly moving `*-latest` hands every
  consumer an unreviewed upstream commit. A hand-made Release makes the release job
  fail after images publish. A version bump that skips `package.json` or `uv.lock`
  passes CI.
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
  any change to which keys `comfy.yaml` or a lock accepts, and CLI verbs or flags.
- **Risk:** consumers pin these formats. `VERSIONING.md` says a format break is
  **major**, however small the diff.
- **Response:** flag it and classify it as major or not. Update `skills/comfy-manifest/SKILL.md`
  in the same change, because no test compares it with the CLI.

### 4. Runtime contract

- **Pattern:** env var names and defaults (`PUID`, `PGID`, `COMFY_*`, `CLI_ARGS`),
  volume paths under `/app`, the port, `entrypoint.sh` user, chown and gosu logic,
  the permission steps in `dockerfile.comfy.core`, the volume mounts in
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
  `MCP_VERSION`, the `sam2` commit in `extra-requirements.txt`, the base-image tags in
  `services/*/dockerfile.*`, action versions in workflows, and the `sed` patch to
  upstream `server.py` in `dockerfile.comfy.mcp`.
- **Risk:** executing unreviewed third-party code, or a silent ABI or behavior change.
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
