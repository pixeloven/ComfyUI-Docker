# Build Guide

This guide covers building Docker images, development setup, and contributing to the project.

## 🏗️ Building Docker Images

### Prerequisites
- Docker Engine 20.10+ with BuildKit support
- Docker Compose v2.0+
- For GPU support: NVIDIA Container Toolkit

### Build Commands

```bash
# Build all services
docker compose build

# Build specific service
docker compose build comfy
docker compose build comfy-setup

# Build with no cache (clean build)
docker compose build --no-cache

# Build and start services
docker compose up --build
```

### Build Arguments

The Dockerfiles support various build arguments for customization:

```bash
# Build with specific base image
docker compose build --build-arg BASE_IMAGE=nvidia/cuda:11.8-devel-ubuntu22.04

# Build with specific Python version
docker compose build --build-arg PYTHON_VERSION=3.10
```

## 🛠️ Development Setup

### Local Development

```bash
# 1. Clone repository
git clone https://github.com/AbdBarho/stable-diffusion-webui-docker.git
cd stable-diffusion-webui-docker

# 2. Copy environment template
cp .env.example .env

# 3. Build development images
docker compose build

# 4. Start services in development mode
docker compose --profile comfy up -d

# 5. View logs
docker compose logs -f
```

### Development Workflow

```bash
# Make changes to Dockerfiles or source code
# Rebuild affected services
docker compose build comfy

# Restart services to apply changes
docker compose restart comfy

# Test changes
docker compose logs comfy
```

### Testing Changes Locally

Use [act](https://github.com/nektos/act) to test GitHub Actions workflows:

```bash
# Install act
curl https://raw.githubusercontent.com/nektos/act/master/install.sh | bash

# Test CI workflow
./bin/act push -W .github/workflows/ci.yml

# Test specific job
./bin/act pull_request -j validate-config
```

## 📁 Project Structure

```
stable-diffusion-webui-docker/
├── docker-compose.yml          # Service orchestration
├── .env.example               # Configuration template
├── services/
│   ├── comfy/                 # ComfyUI service
│   │   ├── Dockerfile         # ComfyUI image definition
│   │   ├── entrypoint.sh      # Container startup script
│   │   └── extra_model_paths.yaml
│   └── comfy-setup/           # Model setup service
│       ├── Dockerfile         # Setup image definition
│       ├── entrypoint.sh      # Setup script
│       ├── links.txt          # Model download links
│       └── checksums.sha256   # Model verification
├── docs/                      # Documentation
├── data/                      # Models and config (created at runtime)
└── output/                    # Generated images (created at runtime)
```

## 🔧 Customization

### Adding New Models

1. Add download links to `services/comfy-setup/links.txt`
2. Update checksums in `services/comfy-setup/checksums.sha256`
3. Rebuild setup service: `docker compose build comfy-setup`
4. Run setup: `docker compose --profile comfy-setup up`

### Modifying ComfyUI Configuration

1. Edit `services/comfy/Dockerfile` for system-level changes
2. Edit `services/comfy/entrypoint.sh` for startup configuration
3. Use `.env` file for runtime arguments

### Custom Extensions

Extensions are managed through ComfyUI Manager within the running container.
For persistent custom extensions, modify the Dockerfile to install them during build.

## 🧪 Testing

### Manual Testing

```bash
# Start services
docker compose --profile comfy up -d

# Test web interface
curl -f http://localhost:8188 || echo "Service not ready"

# Test API endpoint
curl -X POST http://localhost:8188/api/v1/queue

# Check service health
docker compose ps
docker compose logs comfy
```

### Automated Testing

The project uses GitHub Actions for CI/CD. Test locally with:

```bash
# Run all CI checks
./bin/act push

# Run specific workflow
./bin/act -W .github/workflows/ci.yml
```

## 🚀 Contributing

### Before Contributing

1. **Create a discussion** first to describe the problem and proposed solution
2. **Fork the repository** and create a feature branch
3. **Test your changes** locally using the build and test procedures above
4. **Update documentation** if your changes affect usage or configuration

### Pull Request Process

1. Ensure all tests pass locally
2. Update relevant documentation
3. Add clear commit messages
4. Submit PR with detailed description
5. Respond to review feedback

### Code Style

- Follow existing patterns in Dockerfiles and scripts
- Use clear, descriptive variable names
- Comment complex logic
- Keep changes minimal and focused

## 🐛 Troubleshooting Build Issues

### Common Problems

**Docker build fails:**
```bash
# Clear Docker cache
docker system prune -a

# Check Docker version
docker --version
docker compose version
```

**Permission errors:**
```bash
# Fix file permissions
sudo chown -R $USER:$USER .

# Check user/group IDs in .env
echo "PUID=$(id -u)" >> .env
echo "PGID=$(id -g)" >> .env
```

**Out of disk space:**
```bash
# Clean up Docker resources
docker system prune -a --volumes

# Check disk usage
df -h
docker system df
```

### Getting Help

1. Check existing [GitHub issues](https://github.com/AbdBarho/stable-diffusion-webui-docker/issues)
2. Review build logs: `docker compose logs`
3. Test with clean environment: `docker system prune -a`
4. Create new issue with:
   - Docker version (`docker --version`)
   - System info (`uname -a`)
   - Build logs
   - Steps to reproduce

---

For usage instructions, see the [main README](../README.md).
For quick commands, see [Quick Reference](QUICK_REFERENCE.md).
