# Testing Guide

This document provides comprehensive guidance for testing the ComfyUI Docker project using the containerized testing approach.

## 🎯 Overview

The ComfyUI Docker project uses a **containerized testing approach** that provides:

- ✅ **Zero Local Dependencies**: Only requires Docker and Docker Compose
- ✅ **Consistent Environment**: Same testing environment everywhere
- ✅ **Complete Isolation**: Tests don't affect the host system
- ✅ **CI/CD Ready**: Perfect for automated pipelines
- ✅ **Cross-Platform**: Works on Linux, macOS, and Windows

## 🚀 Quick Start

### Prerequisites

- Docker installed and running
- Docker Compose v2.0+ (included with Docker Desktop)
- No Python dependencies required locally

### Run All Tests

```bash
# Run the complete test suite
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all
```

### Run Specific Test Categories

```bash
# Docker build validation tests
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner build

# CPU functionality tests
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner cpu

# GPU functionality tests (requires NVIDIA GPU)
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner gpu

# Environment configuration tests
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner env

# Integration and workflow tests
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner integration
```

## 📋 Test Categories

### 1. Build Tests (`build`)
- **Purpose**: Validate Docker image builds
- **Coverage**: Dockerfile syntax, dependency installation, image layers
- **Files**: `tests/test_docker_build.py`

### 2. CPU Tests (`cpu`)
- **Purpose**: Test CPU-only functionality
- **Coverage**: Service startup, API availability, CPU inference
- **Files**: `tests/test_comfy_cpu.py`

### 3. GPU Tests (`gpu`)
- **Purpose**: Test GPU functionality (requires NVIDIA GPU)
- **Coverage**: CUDA availability, GPU inference, memory management
- **Files**: `tests/test_comfy_gpu.py`

### 4. Environment Tests (`env`)
- **Purpose**: Validate configuration handling
- **Coverage**: Environment variables, CLI arguments, profiles
- **Files**: `tests/test_env_configuration.py`

### 5. Integration Tests (`integration`)
- **Purpose**: Test service interactions and workflows
- **Coverage**: Service switching, data persistence, API workflows
- **Files**: `tests/test_integration.py`

## 🔧 Advanced Usage

### Verbose Output

```bash
# Run tests with detailed output
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all --verbose
```

### Building Test Container

```bash
# Build the test container (useful for development)
docker compose -f tests/docker-compose.test.yml build test-runner

# Force rebuild without cache
docker compose -f tests/docker-compose.test.yml build --no-cache test-runner
```

### Test Result Storage

```bash
# Run tests with database for result storage
docker compose -f tests/docker-compose.test.yml --profile test-with-db up -d test-db
docker compose -f tests/docker-compose.test.yml --profile test-with-db run --rm test-runner all
docker compose -f tests/docker-compose.test.yml --profile test-with-db down
```

### Cleanup

```bash
# Clean up test environment
docker compose -f tests/docker-compose.test.yml down --remove-orphans --volumes

# Remove test images
docker image rm comfy-test-runner || true
```

## 🐍 Alternative: Python Runner

For development environments with Python dependencies installed:

### Setup

```bash
# Install test dependencies
pip install -r tests/requirements.txt
pip install -r tests/runner-requirements.txt
```

### Usage

```bash
# Run tests directly with Python runner
python3 tests/test_runner.py all
python3 tests/test_runner.py build --verbose
python3 tests/test_runner.py cpu
```

## 🔍 Debugging Test Failures

### View Test Logs

```bash
# Run with verbose output to see detailed logs
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all --verbose
```

### Interactive Debugging

```bash
# Start test container with shell access
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner bash

# Inside container, run tests manually
python3 tests/test_runner.py build --verbose
```

### Check Service Logs

```bash
# View ComfyUI service logs during tests
docker compose logs -f comfy
docker compose logs -f comfy-cpu
```

## 📊 Test Configuration

### Environment Variables

The test environment supports these configuration options:

```bash
# Set custom test timeout
PYTEST_TIMEOUT=300 docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all

# Enable debug mode
DEBUG=1 docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all

# Skip GPU tests
SKIP_GPU_TESTS=1 docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all
```

### Test Profiles

- **`test`**: Basic testing environment (test-runner only)
- **`test-with-db`**: Testing with PostgreSQL database for result storage

## 🚨 Troubleshooting

### Common Issues

1. **Docker Socket Permission Denied**
   ```bash
   # On Linux, ensure user is in docker group
   sudo usermod -aG docker $USER
   # Log out and back in
   ```

2. **Port Conflicts**
   ```bash
   # Stop conflicting services
   docker compose down --remove-orphans
   ```

3. **Out of Disk Space**
   ```bash
   # Clean up Docker resources
   docker system prune -f
   docker volume prune -f
   ```

4. **GPU Tests Failing**
   ```bash
   # Check NVIDIA Docker runtime
   docker run --rm --gpus all nvidia/cuda:11.8-base-ubuntu20.04 nvidia-smi
   ```

### Getting Help

- Check test logs with `--verbose` flag
- Review Docker Compose configuration in `tests/docker-compose.test.yml`
- Examine individual test files in `tests/` directory
- Verify Docker and Docker Compose versions

## 📈 Performance Tips

1. **Use Docker Layer Caching**: Build test container once, reuse for multiple test runs
2. **Parallel Testing**: Tests run in parallel by default via pytest
3. **Resource Limits**: Test containers have memory limits to prevent resource exhaustion
4. **Volume Caching**: Test cache volume improves subsequent test runs

## 🔄 CI/CD Integration

The containerized testing approach is designed for CI/CD pipelines and is used in all project workflows:

### GitHub Actions Integration

```yaml
# Example GitHub Actions workflow step
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Build test container
        run: |
          docker compose -f tests/docker-compose.test.yml build test-runner

      - name: Run tests
        run: |
          docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all --verbose

      - name: Cleanup
        if: always()
        run: |
          docker compose -f tests/docker-compose.test.yml down --remove-orphans --volumes
```

### Current CI/CD Usage

The project's CI/CD pipelines use this testing approach in:

- **Main CI/CD** (`ci.yml`): Full test suite for main branch pushes
- **PR Validation** (`pr-validation.yml`): Quick validation for pull requests
- **Release Pipeline** (`release.yml`): Comprehensive testing before releases
- **Maintenance** (`maintenance.yml`): Automated dependency and security checks

### Benefits for CI/CD

- ✅ **Zero Dependencies**: No need to install Python or test dependencies in CI
- ✅ **Consistent Environment**: Same testing environment across all CI runs
- ✅ **Fast Startup**: Docker layer caching speeds up subsequent runs
- ✅ **Parallel Execution**: Easy to run different test categories in parallel
- ✅ **Artifact Collection**: Test results automatically collected in volumes

For complete CI/CD pipeline documentation, see [CI/CD Guide](CI_CD_GUIDE.md).
