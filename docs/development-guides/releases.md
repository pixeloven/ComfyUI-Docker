# Release Process

This document describes the version release process for ComfyUI-Docker, including how to create new releases and how the automated release pipeline works.

## Overview

The project uses semantic versioning (MAJOR.MINOR.PATCH) and automated releases triggered by Git tags. The [PaulHatch/semantic-version](https://github.com/PaulHatch/semantic-version) action automatically determines version bumps based on commit messages containing `(MAJOR)` or `(MINOR)` patterns. When a version tag is pushed, the CI/CD pipeline automatically builds and publishes Docker images with that version. The [update-semver action](https://github.com/marketplace/actions/update-semver) automatically creates major and minor version tags for easier version management.

## Version Management

### Current Version
The current version is stored in the `VERSION` file at the root of the repository. This serves as the single source of truth for the project version.

### Version Format
- **MAJOR**: Breaking changes that require migration (use `(MAJOR)` in commit message)
- **MINOR**: New features in a backward-compatible manner (use `(MINOR)` in commit message)
- **PATCH**: Backward-compatible bug fixes (default)

Examples: `1.0.0`, `1.2.3`, `2.0.0`

### Commit Message Patterns
The semantic versioning system automatically detects version changes based on commit messages:

- **Major Version**: Include `(MAJOR)` in commit message
  ```bash
  git commit -m "Breaking change: new API (MAJOR)"
  ```

- **Minor Version**: Include `(MINOR)` in commit message
  ```bash
  git commit -m "Add new feature (MINOR)"
  ```

- **Patch Version**: Default behavior (no special pattern needed)
  ```bash
  git commit -m "Fix bug in authentication"
  ```

## Release Process

### 1. Prepare for Release

Before creating a release, ensure your working directory is clean:

```bash
git status
```

If there are uncommitted changes, either commit them or stash them.

### 2. Create a Release

There are two ways to create a release:

#### Option A: Manual Tagging
Simply create and push a version tag:

```bash
git tag v1.0.1
git push origin v1.0.1
```

#### Option B: Automatic Version Detection
Use commit message patterns to indicate version changes:

```bash
# For major releases (breaking changes)
git commit -m "Breaking change: new API (MAJOR)"

# For minor releases (new features)
git commit -m "Add new feature (MINOR)"

# For patch releases (bug fixes) - default
git commit -m "Fix bug in authentication"

# Then tag the release
git tag v1.0.1
git push origin v1.0.1
```

### 3. Automated Release

Once the tag is pushed, the GitHub Actions workflow will automatically:

1. **Analyze** commit history using PaulHatch/semantic-version to determine version type
2. **Build** all Docker images with the version tag
3. **Push** images to GitHub Container Registry
4. **Create major/minor tags** (e.g., `v1`, `v1.2`) via update-semver action
5. **Create** a GitHub release with notes

## Docker Images

Each release creates the following versioned images:

- `ghcr.io/pixeloven/comfyui-docker/runtime:cuda-v<VERSION>`
- `ghcr.io/pixeloven/comfyui-docker/runtime:cpu-v<VERSION>`
- `ghcr.io/pixeloven/comfyui-docker/core:cuda-v<VERSION>`
- `ghcr.io/pixeloven/comfyui-docker/core:cpu-v<VERSION>`
- `ghcr.io/pixeloven/comfyui-docker/complete:cuda-v<VERSION>`
- `ghcr.io/pixeloven/comfyui-docker/sageattention-builder:v<VERSION>`

### Version Tags

The update-semver action automatically creates additional tags for easier version management:

- **Full version**: `v1.2.3` (specific patch release)
- **Minor version**: `v1.2` (latest patch in minor version)
- **Major version**: `v1` (latest minor in major version)

This allows users to pin to specific levels of stability:
- `v1.2.3` - Exact version
- `v1.2` - Latest patch in 1.2.x series
- `v1` - Latest minor in 1.x.x series

## Using Versioned Images

### Docker Compose

Specify a specific version:

```bash
# Exact version
COMFY_IMAGE=ghcr.io/pixeloven/comfyui-docker/core:cuda-v1.0.1 docker compose up -d

# Latest patch in minor version
COMFY_IMAGE=ghcr.io/pixeloven/comfyui-docker/core:cuda-v1.0 docker compose up -d

# Latest minor in major version
COMFY_IMAGE=ghcr.io/pixeloven/comfyui-docker/core:cuda-v1 docker compose up -d
```

### Docker Run

```bash
docker run -d \
  --name comfyui \
  -p 8188:8188 \
  ghcr.io/pixeloven/comfyui-docker/core:cuda-v1.0.1
```

## Release Notes

Release notes are automatically generated from Git commits and include:

- **What's New**: List of commits since the last release
- **Docker Images**: All available images for the release
- **Quick Start**: Usage examples
- **Full Changelog**: Link to GitHub commit history

### Customizing Release Notes

You can edit the generated `RELEASE_NOTES.md` file before pushing the tag to customize the release notes.

## Manual Release Process

If you need to create a release manually:

1. Create and push a tag: `git tag v1.0.1 && git push origin v1.0.1`
2. The automated workflow will handle the rest

## Troubleshooting

### Version Already Exists
If you get an error about a tag already existing:

```bash
# Check existing tags
git tag -l | grep v1.0.1

# Delete local tag if needed
git tag -d v1.0.1

# Delete remote tag if needed
git push origin --delete v1.0.1
```

### Build Failures
If the automated build fails:

1. Check the GitHub Actions logs
2. Verify the Docker Bake configuration
3. Ensure all dependencies are available
4. Retry by pushing the tag again

### Version File Issues
The VERSION file is no longer used for version management. The PaulHatch/semantic-version action determines versions automatically from commit history and tags.

## Best Practices

1. **Use commit message patterns** for automatic version detection
2. **Test before releasing** by building images locally
3. **Use semantic versioning** appropriately
4. **Keep the main branch stable** - use feature branches for development
5. **Tag releases** when ready to publish

## CI/CD Pipeline

The release process is fully automated through GitHub Actions:

- **Trigger**: Push of version tag (e.g., `v1.0.1`)
- **Analysis**: PaulHatch/semantic-version determines version type from commit history
- **Build**: All Docker images with version tags
- **Push**: Images to GitHub Container Registry
- **Tags**: update-semver creates major/minor version tags
- **Release**: GitHub release with notes

The pipeline ensures reproducible builds and consistent versioning across all components. 