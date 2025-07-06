# Development

Development setup and contributing to ComfyUI Docker.

## Setup

```bash
# Clone and setup
git clone https://github.com/pixeloven/ComfyUI-Docker.git
cd ComfyUI-Docker
cp .env.example .env

# Build images
docker compose build
```

## Development Workflow

```bash
# Start development environment
docker compose --profile comfy up -d

# Monitor logs
docker compose logs -f

# Make changes to Dockerfiles or config
# Rebuild affected services
docker compose build comfy

# Test changes
docker compose restart
```

## Testing

### Local Testing
```bash
# Test GPU service
docker compose --profile comfy up -d
curl -f http://localhost:8188

# Test CPU service
docker compose down
docker compose --profile comfy-cpu up -d
curl -f http://localhost:8188
```

### CI Testing with Act

Act lets you run GitHub Actions workflows locally.

#### Install Act
```bash
# Install act in project directory
curl https://raw.githubusercontent.com/nektos/act/master/install.sh | bash

# Verify installation
./bin/act --version
```

#### Run CI Tests
```bash
# List available workflows
./bin/act --list

# Test main CI workflow
./bin/act push -W .github/workflows/ci.yml

# Test specific job
./bin/act push -W .github/workflows/ci.yml -j validate-config

# Dry run (preview what would execute)
./bin/act --dry-run
```

#### Troubleshooting Act
```bash
# Verbose output for debugging
./bin/act --verbose

# Check Docker access
docker info

# Fix permissions if needed
chmod +x ./bin/act
```

## Contributing

### Before Contributing
1. Create a discussion describing the problem and solution
2. Fork the repository and create a feature branch
3. Test your changes locally
4. Open a pull request

### Guidelines
- Follow existing code style and patterns
- Include tests for new features
- Update documentation if needed
- Keep commits focused and descriptive

### Common Tasks

#### Adding Models
1. Add download links to `services/comfy-setup/links.txt`
2. Update checksums in `services/comfy-setup/checksums.sha256`
3. Rebuild: `docker compose build comfy-setup`
4. Test: `docker compose --profile comfy-setup up`

#### Modifying Configuration
- **System changes**: Edit `services/comfy/Dockerfile`
- **Startup config**: Edit `services/comfy/entrypoint.sh`
- **Runtime settings**: Use `.env` file
