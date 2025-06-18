# Local CI Testing

Test GitHub Actions workflows locally using [act](https://github.com/nektos/act).

## Install act

```bash
# Install act locally in the project directory
curl https://raw.githubusercontent.com/nektos/act/master/install.sh | bash
```

## Common Commands

```bash
# List all workflows and jobs
./bin/act --list

# Test PR validation (most common)
./bin/act pull_request -W .github/workflows/pr-validation.yml

# Test main CI workflow
./bin/act push -W .github/workflows/ci.yml

# Test Docker builds
./bin/act push -W .github/workflows/docker.yml

# Test specific job only
./bin/act pull_request -W .github/workflows/pr-validation.yml -j quick-validation
```

## Configuration

The repository includes a `.actrc` file with optimized settings for this project.

## Troubleshooting

**Docker not running:**
```bash
docker info  # Check if Docker is running
```

**Memory issues:**
```bash
# Increase Docker memory limit in Docker Desktop: Settings > Resources > Memory > 8GB+
```

**Need help:**
```bash
./bin/act --help
```

---

For more information: [act documentation](https://github.com/nektos/act)
