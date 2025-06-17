# Testing Guide for ComfyUI CPU Support

This guide provides step-by-step instructions for testing the new CPU support functionality.

## Prerequisites

- Docker and Docker Compose installed
- Python 3.7+ (for running tests)
- Git (for cloning and managing the repository)

## Quick Validation

### 1. Verify Configuration Files

```bash
# Check docker-compose syntax
docker compose config

# Check specific profiles
docker compose --profile comfy config
docker compose --profile comfy-cpu config
```

### 2. Test Docker Builds

```bash
# Build unified image (works for both CPU and GPU)
docker compose --profile comfy build

# Verify image exists
docker images | grep comfy
```

### 3. Test Service Startup

```bash
# Test CPU mode
docker compose --profile comfy-cpu up -d
curl http://localhost:8189  # Should return ComfyUI interface
docker compose --profile comfy-cpu down

# Test GPU mode (if GPU available)
docker compose --profile comfy up -d  
curl http://localhost:8188  # Should return ComfyUI interface
docker compose --profile comfy down
```

## Comprehensive Testing

### 1. Run Automated Tests

```bash
# Make test script executable
chmod +x scripts/test.sh

# Run all tests
./scripts/test.sh all

# Run specific test categories
./scripts/test.sh build
./scripts/test.sh env
./scripts/test.sh cpu
```

### 2. Manual Testing Scenarios

#### Scenario 1: CPU Mode Configuration

```bash
# Create .env file
cp .env.example .env

# Edit .env to set CPU mode
echo "COMFY_CLI_ARGS=--cpu" >> .env

# Start service
docker compose --profile comfy-cpu up -d

# Verify service
curl -s http://localhost:8189 | grep -i comfy

# Check logs for CPU mode indicator
docker compose logs comfy-cpu | grep "CPU-only mode"

# Cleanup
docker compose down
```

#### Scenario 2: GPU Mode with Low VRAM

```bash
# Configure for low VRAM
echo "COMFY_CLI_ARGS=--lowvram" > .env

# Start GPU service
docker compose --profile comfy up -d

# Verify service
curl -s http://localhost:8188 | grep -i comfy

# Check logs
docker compose logs comfy | grep "GPU mode"

# Cleanup
docker compose down
```

#### Scenario 3: Concurrent Operation

```bash
# Set different CLI args for testing
echo "COMFY_CLI_ARGS=" > .env

# Start both services
docker compose --profile comfy up -d
docker compose --profile comfy-cpu up -d

# Verify both are running
curl -s http://localhost:8188 | head -1
curl -s http://localhost:8189 | head -1

# Check both containers
docker ps | grep comfy

# Cleanup
docker compose down
```

### 3. Using Makefile

```bash
# Test Makefile targets
make help
make config
make build

# Test service management
make up-cpu
sleep 30  # Wait for startup
curl http://localhost:8189
make down

make up-gpu  # Only if GPU available
sleep 30
curl http://localhost:8188
make down
```

## Troubleshooting Tests

### Common Issues and Solutions

#### 1. Port Conflicts

```bash
# Check if ports are in use
netstat -tlnp | grep :8188
netstat -tlnp | grep :8189

# If ports are busy, modify docker-compose.yml or stop conflicting services
```

#### 2. Docker Build Failures

```bash
# Clean Docker cache
docker system prune -f

# Rebuild with no cache
docker compose --profile comfy-cpu build --no-cache
docker compose --profile comfy build --no-cache
```

#### 3. Test Environment Issues

```bash
# Create fresh test environment
cd tests
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run tests with verbose output
pytest -v --tb=short
```

#### 4. Permission Issues

```bash
# Fix script permissions
chmod +x scripts/test.sh

# Fix data directory permissions
sudo chown -R $USER:$USER data/
```

## Validation Checklist

Use this checklist to verify the implementation:

### Build Validation
- [ ] Unified image builds successfully
- [ ] Image has correct tag (comfy:v0.3.39)
- [ ] Image contains onnxruntime-gpu (handles both GPU and CPU)
- [ ] No separate CPU/GPU images (simplified approach)

### Configuration Validation
- [ ] .env.example contains CPU configuration examples
- [ ] docker-compose.yml has both comfy and comfy-cpu profiles
- [ ] Services use different ports (8188 vs 8189)
- [ ] CPU service has default --cpu CLI args
- [ ] GPU service has GPU device allocation

### Functionality Validation
- [ ] CPU service starts and responds on port 8189
- [ ] GPU service starts and responds on port 8188
- [ ] Both services can run simultaneously
- [ ] CLI args are properly passed to ComfyUI
- [ ] Logs show correct mode indicators

### Test Validation
- [ ] All automated tests pass
- [ ] Build tests validate image creation
- [ ] Environment tests validate configuration
- [ ] Integration tests validate service interaction

## Performance Testing

### Basic Performance Comparison

```bash
# Start CPU service
docker compose --profile comfy-cpu up -d

# Time a simple API call
time curl -s http://localhost:8189/system_stats

# Start GPU service (if available)
docker compose --profile comfy up -d

# Compare response time
time curl -s http://localhost:8188/system_stats
```

### Memory Usage Monitoring

```bash
# Monitor CPU service memory
docker stats comfy-cpu

# Monitor GPU service memory (if available)
docker stats comfy
```

## Reporting Issues

If you encounter issues during testing:

1. **Collect logs**:
   ```bash
   docker compose logs > comfy-logs.txt
   ```

2. **System information**:
   ```bash
   docker version > system-info.txt
   docker compose version >> system-info.txt
   uname -a >> system-info.txt
   ```

3. **Test output**:
   ```bash
   ./scripts/test.sh all > test-output.txt 2>&1
   ```

4. **Configuration**:
   ```bash
   docker compose config > compose-config.yml
   ```

Include these files when reporting issues for faster troubleshooting.
