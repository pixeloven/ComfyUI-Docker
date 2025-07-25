# CI/CD with Docker Bake

Our CI/CD pipeline uses Docker Bake for efficient image building with proper caching and dependency management.

## Workflows

### Main CI (`.github/workflows/ci.yml`)
- **Triggers**: Push to `main`, PRs, changes to services/docker files
- **Jobs**: 
  - `validate-config`: Validates configs and Docker Bake syntax
  - `build-images`: Builds base images using bake group `base` (runtime + base ComfyUI images)
  - `test-cpu-runtime`: Tests CPU runtime startup (PRs only)
  - `pr-summary`: Provides PR validation summary

## Docker Bake Groups

| Group | Builds |
|-------|--------|
| `all` | All images (runtime-nvidia, runtime-cpu, comfy-nvidia, comfy-cpu, comfy-cuda-extended, sageattention-builder) |
| `base` | Base images only (runtime-nvidia, runtime-cpu, comfy-nvidia, comfy-cpu) |
| `runtime` | Runtime images only |
| `nvidia` | NVIDIA images (runtime-nvidia, comfy-nvidia, comfy-cuda-extended) |
| `cpu` | CPU images (runtime-cpu, comfy-cpu) |
| `comfy` | ComfyUI images (comfy-nvidia, comfy-cpu) |

## Local Testing with Act

Act lets you run GitHub Actions workflows locally.

### Install Act
```bash
# Install act in project directory
curl https://raw.githubusercontent.com/nektos/act/master/install.sh | bash

# Verify installation
./bin/act --version
```

### Test Workflows
```bash
# List available workflows
./bin/act --list

# Test main CI workflow
./bin/act push -W .github/workflows/ci.yml

# Test specific job
./bin/act push -W .github/workflows/ci.yml -j validate-config

# Dry run (preview what would execute)
./bin/act --dry-run
```

### Troubleshooting Act
```bash
# Verbose output for debugging
./bin/act --verbose

# Check Docker access
docker info

# Fix permissions if needed
chmod +x ./bin/act
```

## Usage Examples

### Build All Images
```bash
docker buildx bake --file docker-bake.hcl all
```

### Build Specific Group
```bash
docker buildx bake --file docker-bake.hcl nvidia
```

### Build Single Target
```bash
docker buildx bake --file docker-bake.hcl runtime-cpu
```

### Validate Configuration
```bash
docker buildx bake --file docker-bake.hcl --print
```

## Caching Strategy

- **GitHub Actions Cache**: Fast local caching
- **Registry Cache**: Persistent caching across builds
- **Inline Cache**: Embedded in final images

## Best Practices

1. **Use Groups**: Prefer building groups over individual targets
2. **Test Locally**: Use Act to test workflows before pushing
3. **Monitor Cache**: Track build times and cache effectiveness
4. **Version Releases**: Use semantic versioning for releases
