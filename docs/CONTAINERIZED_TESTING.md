# Containerized Testing

This document describes the containerized testing approach that eliminates all local Python dependencies and provides a consistent testing environment.

## 🎯 **Overview**

The containerized testing suite runs all tests inside a dedicated Docker container, providing:

- ✅ **Zero Local Dependencies**: Only requires Docker
- ✅ **Consistent Environment**: Same environment everywhere
- ✅ **Complete Isolation**: Tests don't affect host system
- ✅ **CI/CD Ready**: Perfect for automated pipelines

## 🚀 **Quick Start**

### **Primary Method (Recommended)**
```bash
# Run all tests using docker-compose.test.yml
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all
```

### **Specific Test Categories**
```bash
# Run specific test types
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner build
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner cpu
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner gpu
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner env
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner integration
```

### **With Verbose Output**
```bash
# Run tests with detailed output
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all --verbose
```

## 📦 **Setup**

### **Prerequisites**
- Docker installed and running
- No Python dependencies required locally

### **Build Test Container**
```bash
# Build the test container
docker compose -f tests/docker-compose.test.yml build test-runner

# Force rebuild without cache
docker compose -f tests/docker-compose.test.yml build --no-cache test-runner
```

## 🔧 **Usage**

### **Basic Commands**
```bash
# Run all tests (primary method)
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all

# Run specific test categories
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner build
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner cpu
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner gpu
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner env
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner integration

# Enable verbose output
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all --verbose

# Clean up test environment
docker compose -f tests/docker-compose.test.yml down --remove-orphans --volumes
```

### **Alternative: Direct Python Runner**
```bash
# For development environments with Python dependencies installed
python3 tests/test_runner.py all
python3 tests/test_runner.py build --verbose
```

## 📁 **Architecture**

### **File Structure**
```
tests/
├── Dockerfile                 # Test container definition
├── docker-compose.test.yml    # Primary test configuration (MAIN INTERFACE)
├── requirements.txt           # Test dependencies
├── runner-requirements.txt    # Test runner dependencies
├── test_runner.py             # Python test runner (runs in container)
├── test_*.py                  # Test files
└── conftest.py                # Test configuration

docs/
├── TESTING_GUIDE.md           # Comprehensive testing documentation
└── CONTAINERIZED_TESTING.md   # This file
```

### **Container Environment**
- **Base Image**: `python:3.9-slim`
- **Dependencies**: pytest, requests, docker, click, rich
- **Tools**: curl, netcat for connectivity testing
- **Volumes**: Docker socket, project root, test results
- **Network**: Isolated test network

## 🔄 **Testing Approach**

The project now uses a **single, unified testing approach** via `docker-compose.test.yml`:

1. **🐳 Primary Method**: Docker Compose Test Configuration
   - **Command**: `docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all`
   - **Benefits**: Complete isolation, no local dependencies, consistent environment
   - **Requirements**: Docker and Docker Compose only

2. **🐍 Alternative**: Direct Python Runner (for development)
   - **Command**: `python3 tests/test_runner.py all`
   - **Benefits**: Faster startup, direct debugging
   - **Requirements**: Python 3 + test dependencies installed locally

## 🛠️ **Environment Variables**

### **Test Configuration**
```bash
# Set custom test timeout
PYTEST_TIMEOUT=300 docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all

# Enable debug mode
DEBUG=1 docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all

# Skip GPU tests
SKIP_GPU_TESTS=1 docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner all
```

### **Container Environment**
```bash
# Project root inside container
PROJECT_ROOT=/workspace

# Tests directory inside container
TESTS_DIR=/workspace/tests

# Docker socket access
DOCKER_HOST=unix:///var/run/docker.sock

# Test cache directory
PYTEST_CACHE_DIR=/app/.cache/pytest
```

## 🐛 **Troubleshooting**

### **Docker Issues**
```bash
# Check if Docker is running
docker info

# Check if test container exists
docker images | grep test-runner

# Rebuild test container
docker compose -f tests/docker-compose.test.yml build --no-cache test-runner
```

### **Permission Issues**
```bash
# Check Docker socket permissions (most common issue)
ls -la /var/run/docker.sock

# Ensure user is in docker group (Linux)
sudo usermod -aG docker $USER
# Log out and back in after adding to group

# Test Docker access
docker info
```

### **Network Issues**
```bash
# Check if services are accessible from test container
docker compose -f tests/docker-compose.test.yml --profile test run --rm test-runner env

# Manual connectivity test
docker run --rm --network host alpine:latest ping localhost
```

## 📊 **Comparison with Other Approaches**

| Feature | Containerized | Python Runner | Bash Runner |
|---------|---------------|---------------|-------------|
| Local Dependencies | ✅ None | ❌ Python + packages | ✅ Minimal |
| Consistency | ✅ Perfect | ⚠️ Environment dependent | ❌ Variable |
| Isolation | ✅ Complete | ❌ Shared environment | ❌ Shared environment |
| Setup Time | ⚠️ Container build | ⚠️ Dependency install | ✅ Immediate |
| CI/CD Ready | ✅ Perfect | ✅ Good | ⚠️ Limited |
| Cross-Platform | ✅ Docker everywhere | ✅ Python everywhere | ❌ Unix only |
| Resource Usage | ⚠️ Container overhead | ✅ Minimal | ✅ Minimal |

## 🎯 **Benefits**

### **For Developers**
- ✅ **Zero Setup**: Just need Docker, no Python environment
- ✅ **Consistent Results**: Same as CI/CD environment
- ✅ **Clean System**: No test dependencies on host
- ✅ **Easy Cleanup**: Container cleanup handles everything

### **For CI/CD**
- ✅ **Reliable**: Consistent environment across all runs
- ✅ **Fast**: No dependency installation time
- ✅ **Cacheable**: Docker layer caching
- ✅ **Scalable**: Easy parallel execution

### **For Maintenance**
- ✅ **Version Controlled**: Test environment is in Git
- ✅ **Reproducible**: Exact environment recreation
- ✅ **Portable**: Works anywhere Docker runs
- ✅ **Updatable**: Easy environment updates

## 🚀 **Advanced Usage**

### **Custom Test Container**
```bash
# Build with custom tag
docker build -t my-comfy-tests tests/

# Run with custom container
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock my-comfy-tests all
```

### **Test Result Extraction**
```bash
# Mount results directory
docker compose -f tests/docker-compose.test.yml --profile test run --rm \
  -v $(pwd)/test-results:/app/test-results \
  test-runner all
```

### **Development Mode**
```bash
# Mount source for live development
docker compose -f tests/docker-compose.test.yml --profile test run --rm \
  -v $(pwd)/tests:/app/tests \
  test-runner all
```

## 🎯 **Conclusion**

Containerized testing provides the ultimate in consistency and portability while eliminating all local dependency requirements. It's the recommended approach for both development and CI/CD environments, offering a clean separation between the testing infrastructure and the host system.
