# Local CI Testing

Test GitHub Actions workflows locally using [act](https://github.com/nektos/act) before pushing changes.

## 📋 Overview

- **Quick Setup** - Install and run act for immediate testing
- **Common Commands** - Essential act commands for workflow testing
- **Configuration** - Customizing act behavior for your environment
- **Troubleshooting** - Resolving common act and workflow issues

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

### act-Specific Issues

**act binary not executable:**
```bash
chmod +x ./bin/act
```

**Workflow failures:**
```bash
# Run with verbose output for debugging
./bin/act --verbose

# Check specific job logs
./bin/act -j job-name --verbose

# Dry run to see what would execute
./bin/act --dry-run
```

**Docker issues with act:**
```bash
# Verify Docker is accessible
docker info

# Check if act can access Docker
./bin/act --list
```

## 💡 Best Practices

- **Test before pushing**: Always run CI locally before committing
- **Use specific workflows**: Test only the workflows you've changed with `-W` flag
- **Use dry run**: Preview what act will do with `--dry-run`
- **Check logs**: Use `--verbose` for detailed debugging information



---

**[⬆ Back to Documentation](README.md)** | **[🏠 Main README](../README.md)** | **[🐛 Report Issues](https://github.com/pixeloven/ComfyUI-Docker/issues)**
