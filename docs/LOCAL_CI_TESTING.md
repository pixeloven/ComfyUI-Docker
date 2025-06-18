# Local CI Testing Guide

Test GitHub Actions workflows locally before pushing changes using [act](https://github.com/nektos/act).

## 🚀 Quick Start

### 1. Install act

**macOS:**
```bash
brew install act
```

**Linux:**
```bash
curl https://raw.githubusercontent.com/nektos/act/master/install.sh | sudo bash
```

**Windows:**
```bash
choco install act-cli
```

**Manual Installation:**
Download from [GitHub releases](https://github.com/nektos/act/releases)

### 2. Run CI Locally

```bash
# Test PR validation (most common)
act pull_request -W .github/workflows/pr-validation.yml

# Test main CI workflow
act push -W .github/workflows/ci.yml

# Test Docker build workflow
act push -W .github/workflows/docker.yml
```

## 📋 Available Workflows

| Workflow | Command | Description |
|----------|---------|-------------|
| PR Validation | `act pull_request -W .github/workflows/pr-validation.yml` | Quick validation for pull requests |
| Main CI | `act push -W .github/workflows/ci.yml` | Full CI pipeline with tests |
| Docker Build | `act push -W .github/workflows/docker.yml` | Docker image building |
| Maintenance | `act workflow_dispatch -W .github/workflows/maintenance.yml` | Scheduled maintenance tasks |

## 🎯 Testing Specific Jobs

```bash
# Test only the build job in CI workflow
act push -W .github/workflows/ci.yml -j build-and-test

# Test only quick validation in PR workflow
act pull_request -W .github/workflows/pr-validation.yml -j quick-validation

# Test security checks
act pull_request -W .github/workflows/pr-validation.yml -j security-check

# List all available jobs
act --list
```

## ⚙️ Configuration

The repository includes a `.actrc` file with optimized settings:

- Uses GitHub's official runner images
- Enables Docker socket binding for container tests
- Sets up artifact server for debugging
- Configures verbose output and container reuse

## 🐛 Troubleshooting

### Docker Socket Issues
```bash
# Ensure Docker is running
docker info

# Check Docker socket permissions (Linux)
sudo chmod 666 /var/run/docker.sock
```

### Memory Issues
```bash
# Increase Docker memory limit
# Docker Desktop: Settings > Resources > Memory > 8GB+

# Or run with limited jobs
./scripts/run-ci-locally.sh pr-validation quick-validation
```

### Network Issues
```bash
# Use host network if containers can't communicate
act --use-gitignore=false --network host
```

## 💡 Tips

1. **Start Small**: Test individual jobs before running full workflows
2. **Use Caching**: act reuses containers by default for faster runs
3. **Check Logs**: Use `--verbose` flag for detailed output
4. **Clean Up**: Remove act containers with `docker system prune`
5. **List Jobs**: Use `act --list` to see all available workflows and jobs

## ⚠️ Limitations

- **Secrets**: Local testing uses dummy secrets
- **Environment**: May differ slightly from GitHub Actions
- **Performance**: Local runs may be slower than GitHub
- **Services**: Some GitHub-specific services won't work locally

## 🔄 Workflow Development

When modifying workflows:

1. **Test locally first**: `act [event] -W .github/workflows/[workflow].yml`
2. **Fix issues locally**: Faster iteration than pushing to GitHub
3. **Push when working**: Final validation on GitHub Actions
4. **Monitor GitHub runs**: Ensure everything works in production

## 📖 Common Commands

```bash
# Quick reference for this project
act --list                                                    # List all workflows
act pull_request -W .github/workflows/pr-validation.yml      # Test PR validation
act push -W .github/workflows/ci.yml                         # Test main CI
act push -W .github/workflows/docker.yml                     # Test Docker builds
act pull_request -W .github/workflows/pr-validation.yml -j quick-validation  # Test specific job
```

## 📚 Further Reading

- [act Documentation](https://github.com/nektos/act)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Docker in GitHub Actions](https://docs.github.com/en/actions/using-containerized-services)

---

*Test locally, deploy confidently!*
