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

# Test main CI workflow
./bin/act push -W .github/workflows/ci.yml

# Test release workflow
./bin/act push -W .github/workflows/release.yml

# Test specific job only
./bin/act pull_request -W .github/workflows/ci.yml -j validate-config
```

## Configuration

Act uses default settings that work well for this project. You can create a `.actrc` file in the repository root if you need custom configuration.

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
