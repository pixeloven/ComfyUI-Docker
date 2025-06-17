# Migration Guide: From Scripts to Docker Compose Testing

This guide helps users migrate from the previous script-based testing approach to the new unified docker-compose.test.yml configuration.

## 🔄 What Changed

### Removed Files
- ❌ `scripts/test.sh` - Main test script
- ❌ `Makefile` - Build and test convenience targets
- ❌ `tests/test_containerized.sh` - Containerized test wrapper
- ❌ `tests/install_test_runner.sh` - Installation script

### New Approach
- ✅ `tests/docker-compose.test.yml` - **Single source of truth** for testing
- ✅ `docs/TESTING_GUIDE.md` - Comprehensive testing documentation
- ✅ Updated CI/CD workflows using containerized testing

## 📋 Command Migration

### Old Commands → New Commands

#### Running All Tests
```bash
# OLD
./scripts/test.sh all
make test

# NEW
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all
```

#### Running Specific Test Categories
```bash
# OLD
./scripts/test.sh build
./scripts/test.sh cpu
./scripts/test.sh gpu
make test-cpu
make test-gpu

# NEW
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner build
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner cpu
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner gpu
```

#### Verbose Output
```bash
# OLD
./scripts/test.sh all --verbose

# NEW
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all --verbose
```

#### Building and Testing
```bash
# OLD
make build
make test

# NEW
docker compose --profile comfy build
docker compose --profile comfy-cpu build
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all
```

#### Service Management
```bash
# OLD
make up-gpu
make up-cpu
make down

# NEW
docker compose --profile comfy up -d
docker compose --profile comfy-cpu up -d
docker compose down --remove-orphans
```

#### Cleanup
```bash
# OLD
make clean

# NEW
docker compose down --remove-orphans
docker compose -f tests/docker-compose.test.yml down --remove-orphans --volumes
docker system prune -f
```

## 🐍 Python Runner Alternative

For development environments, you can still use the Python runner directly:

```bash
# Install dependencies (one-time setup)
pip install -r tests/requirements.txt
pip install -r tests/runner-requirements.txt

# Run tests
python3 tests/test_runner.py all
python3 tests/test_runner.py build --verbose
```

## 🔧 Development Workflow

### Old Workflow
```bash
# 1. Install dependencies
./tests/install_test_runner.sh

# 2. Run tests
./scripts/test.sh all

# 3. Build services
make build

# 4. Start services
make up-gpu
```

### New Workflow
```bash
# 1. Run tests (no dependencies needed)
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all

# 2. Build services
docker compose --profile comfy build
docker compose --profile comfy-cpu build

# 3. Start services
docker compose --profile comfy up -d
# or
docker compose --profile comfy-cpu up -d
```

## 📚 Documentation Updates

### Updated Documentation
- ✅ `docs/TESTING_GUIDE.md` - Primary testing documentation
- ✅ `docs/CONTAINERIZED_TESTING.md` - Updated for new approach
- ✅ `docs/CI_CD_GUIDE.md` - Updated CI/CD examples
- ✅ `docs/CPU_SUPPORT.md` - Removed Makefile references
- ✅ `README.md` - Added testing section

### Key Documentation Changes
- All examples now use `docker compose -f tests/docker-compose.test.yml`
- Removed references to removed scripts and Makefile
- Added comprehensive usage examples in docker-compose.test.yml itself
- Updated CI/CD workflow documentation

## 🚀 Benefits of New Approach

### Simplified
- **Single Configuration**: One file (`docker-compose.test.yml`) for all testing
- **No Scripts**: No need to maintain multiple wrapper scripts
- **Clear Documentation**: All usage examples in one place

### More Reliable
- **Zero Dependencies**: Only requires Docker and Docker Compose
- **Consistent Environment**: Same testing environment everywhere
- **Better CI/CD**: Cleaner integration with automated pipelines

### Easier Maintenance
- **Less Code**: Fewer files to maintain and update
- **Better Documentation**: Comprehensive docs with examples
- **Clearer Interface**: Direct docker-compose commands

## 🔍 Troubleshooting Migration

### Common Issues

1. **"Command not found" errors**
   - **Problem**: Trying to use removed scripts
   - **Solution**: Use new docker-compose commands from this guide

2. **"make: command not found"**
   - **Problem**: Makefile was removed
   - **Solution**: Use direct docker-compose commands

3. **Permission denied errors**
   - **Problem**: Docker socket permissions
   - **Solution**: Ensure user is in docker group (Linux) or Docker Desktop is running

4. **Test failures**
   - **Problem**: Different test environment
   - **Solution**: Tests now run in containers; check container logs for details

### Getting Help

- Check the [Testing Guide](TESTING_GUIDE.md) for comprehensive documentation
- Review [docker-compose.test.yml](../tests/docker-compose.test.yml) for usage examples
- See [CI/CD Guide](CI_CD_GUIDE.md) for pipeline integration examples

## ✅ Migration Checklist

- [ ] Update local scripts/aliases to use new docker-compose commands
- [ ] Remove any references to old scripts in documentation
- [ ] Update CI/CD pipelines if using custom workflows
- [ ] Test new commands work in your environment
- [ ] Update team documentation and onboarding guides

## 🎯 Quick Reference

### Most Common Commands
```bash
# Run all tests
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all

# Run specific tests
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner cpu

# Start GPU service
docker compose --profile comfy up -d

# Start CPU service  
docker compose --profile comfy-cpu up -d

# Stop all services
docker compose down --remove-orphans

# Clean up test environment
docker compose -f tests/docker-compose.test.yml down --remove-orphans --volumes
```

This migration provides a cleaner, more maintainable testing approach while preserving all functionality from the previous system.
