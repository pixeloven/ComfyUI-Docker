# Local CI Testing

Test GitHub Actions workflows locally using [act](https://github.com/nektos/act) before pushing changes.

## 🚀 Quick Setup

```bash
# Install act locally in the project directory
curl https://raw.githubusercontent.com/nektos/act/master/install.sh | bash

# Test main CI workflow
./bin/act push -W .github/workflows/ci.yml
```

## 📋 Common Commands

```bash
# List all workflows and jobs
./bin/act --list

# Test main CI workflow
./bin/act push -W .github/workflows/ci.yml

# Test release workflow
./bin/act push -W .github/workflows/release.yml

# Test specific job only
./bin/act pull_request -W .github/workflows/ci.yml -j validate-config

# Dry run (show what would be executed)
./bin/act --dry-run
```

## ⚙️ Configuration

Act uses sensible defaults for this project. For custom configuration, create a `.actrc` file in the repository root:

```bash
# Example .actrc
--container-architecture linux/amd64
--artifact-server-path /tmp/artifacts
```

## 🐛 Troubleshooting

### Common Issues

**Docker not running:**
```bash
docker info  # Verify Docker is running
sudo systemctl start docker  # Linux
# Or start Docker Desktop on macOS/Windows
```

**Memory/resource issues:**
```bash
# Increase Docker memory in Docker Desktop
# Settings > Resources > Memory > 8GB+

# Check available resources
docker system df
docker stats
```

**Permission errors:**
```bash
# Ensure act binary is executable
chmod +x ./bin/act

# Check Docker permissions
docker run hello-world
```

**Workflow failures:**
```bash
# Run with verbose output
./bin/act --verbose

# Check specific job logs
./bin/act -j job-name --verbose
```

## 💡 Best Practices

- **Test before pushing**: Always run CI locally before committing
- **Use specific workflows**: Test only the workflows you've changed
- **Check resource usage**: Monitor Docker memory/CPU during tests
- **Clean up**: Run `docker system prune` periodically

## 🔗 Related Documentation

- **[Build Guide](BUILD.md)** - Development setup and contribution guidelines
- **[Quick Reference](QUICK_REFERENCE.md)** - Essential Docker commands
- **[act documentation](https://github.com/nektos/act)** - Official act documentation

---

**[⬆ Back to Documentation](README.md)** | **[🛠️ Build Guide](BUILD.md)** | **[🏠 Main README](../README.md)**
