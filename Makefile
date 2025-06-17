.PHONY: help build build-cpu build-gpu test test-build test-cpu test-gpu test-env clean up-cpu up-gpu down logs

# Default target
help:
	@echo "ComfyUI Docker Management"
	@echo ""
	@echo "Available targets:"
	@echo "  build      - Build both GPU and CPU images"
	@echo "  build-gpu  - Build GPU image only"
	@echo "  build-cpu  - Build CPU image only"
	@echo ""
	@echo "  up-gpu     - Start ComfyUI GPU service"
	@echo "  up-cpu     - Start ComfyUI CPU service"
	@echo "  down       - Stop all services"
	@echo "  logs       - Show logs for running services"
	@echo ""
	@echo "  test       - Run all tests"
	@echo "  test-build - Run Docker build tests"
	@echo "  test-cpu   - Run CPU mode tests"
	@echo "  test-gpu   - Run GPU mode tests"
	@echo "  test-env   - Run environment configuration tests"
	@echo ""
	@echo "  clean      - Clean up containers and images"
	@echo ""
	@echo "Environment variables:"
	@echo "  COMFY_CLI_ARGS - CLI arguments for ComfyUI"
	@echo "    Examples:"
	@echo "      make up-cpu COMFY_CLI_ARGS='--cpu --force-fp16'"
	@echo "      make up-gpu COMFY_CLI_ARGS='--lowvram'"

# Build targets
build: build-gpu build-cpu

build-gpu:
	@echo "Building ComfyUI GPU image..."
	docker compose --profile comfy build

build-cpu:
	@echo "Building ComfyUI CPU image..."
	docker compose --profile comfy-cpu build

# Service management
up-gpu:
	@echo "Starting ComfyUI GPU service..."
	docker compose --profile comfy up -d
	@echo "ComfyUI GPU available at: http://localhost:8188"

up-cpu:
	@echo "Starting ComfyUI CPU service..."
	docker compose --profile comfy-cpu up -d
	@echo "ComfyUI CPU available at: http://localhost:8189"

down:
	@echo "Stopping all services..."
	docker compose down --remove-orphans

logs:
	docker compose logs -f

# Test targets
test:
	@echo "Running all tests..."
	./scripts/test.sh all

test-build:
	@echo "Running Docker build tests..."
	./scripts/test.sh build

test-cpu:
	@echo "Running CPU mode tests..."
	./scripts/test.sh cpu

test-gpu:
	@echo "Running GPU mode tests..."
	./scripts/test.sh gpu

test-env:
	@echo "Running environment configuration tests..."
	cd tests && python -m pytest test_env_configuration.py -v

# Cleanup
clean:
	@echo "Cleaning up containers and images..."
	docker compose down --remove-orphans
	docker image prune -f
	@echo "Cleanup completed"

# Development helpers
shell-gpu:
	docker compose --profile comfy exec comfy /bin/bash

shell-cpu:
	docker compose --profile comfy-cpu exec comfy-cpu /bin/bash

# Show current configuration
config:
	@echo "Current docker-compose configuration:"
	docker compose config

config-gpu:
	@echo "GPU service configuration:"
	docker compose --profile comfy config

config-cpu:
	@echo "CPU service configuration:"
	docker compose --profile comfy-cpu config
