# ComfyUI-Docker Makefile
# Provides convenient targets for local development and building

.PHONY: help all runtime core cuda cpu clean

# Default target
help: ## Show this help message
	@echo "ComfyUI-Docker Build Targets:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

# Build all images
all: ## Build all images (runtime + core + complete)
	docker buildx bake all

# Runtime images
runtime: ## Build both runtime images (CUDA + CPU)
	docker buildx bake runtime

runtime-cuda: ## Build CUDA runtime image
	docker buildx bake runtime-cuda

runtime-cpu: ## Build CPU runtime image
	docker buildx bake runtime-cpu

# Core images 
core: ## Build core images (runtime + core layers for both CUDA/CPU)
	docker buildx bake core

core-cuda: ## Build CUDA core image
	docker buildx bake core-cuda

core-cpu: ## Build CPU core image
	docker buildx bake core-cpu

# CUDA stack (runtime + core + complete)
cuda: ## Build complete CUDA stack
	docker buildx bake cuda

# CPU stack (runtime + core)
cpu: ## Build complete CPU stack
	docker buildx bake cpu

# Complete images
complete-cuda: ## Build CUDA complete image
	docker buildx bake complete-cuda

# Development targets
dev: ## Build all images with 'dev' label
	IMAGE_LABEL=dev docker buildx bake all

clean: ## Clean build cache and rebuild from scratch
	docker buildx bake all --no-cache

# Utility targets
validate: ## Validate Docker Compose and Bake configurations
	docker compose config --quiet
	docker buildx bake --print all > /dev/null

push: ## Build and push all images to registry
	docker buildx bake all --push

# Local testing
test: ## Start services locally for testing
	docker compose up -d

test-cpu: ## Start CPU services locally for testing
	docker compose --profile cpu up -d

test-complete: ## Start complete services locally for testing
	docker compose --profile complete up -d

stop: ## Stop running services
	docker compose down

logs: ## Show logs from running services
	docker compose logs -f