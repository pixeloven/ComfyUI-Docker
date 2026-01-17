# ComfyUI-Docker Makefile
# Provides convenient targets for local development and building

.PHONY: help all runtime core cuda cpu clean

# Default target
help: ## Show this help message
	@echo "ComfyUI-Docker Build Targets:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

# Build all images
all: ## Build all images (runtime + core + complete) and load to Docker
	docker buildx bake all --load

# Runtime images
runtime: ## Build both runtime images (CUDA + CPU) and load to Docker
	docker buildx bake runtime --load

runtime-cuda: ## Build CUDA runtime image and load to Docker
	docker buildx bake runtime-cuda --load

runtime-cpu: ## Build CPU runtime image and load to Docker
	docker buildx bake runtime-cpu --load

# Core images 
core: ## Build core images (runtime + core layers for both CUDA/CPU) and load to Docker
	docker buildx bake core --load

core-cuda: ## Build CUDA core image and load to Docker
	docker buildx bake core-cuda --load

core-cpu: ## Build CPU core image and load to Docker
	docker buildx bake core-cpu --load

# CUDA stack (runtime + core + complete)
cuda: ## Build complete CUDA stack and load to Docker
	docker buildx bake cuda --load

# CPU stack (runtime + core)
cpu: ## Build complete CPU stack and load to Docker
	docker buildx bake cpu --load

# Complete images
complete-cuda: ## Build CUDA complete image and load to Docker
	docker buildx bake complete-cuda --load

# Development targets
dev: ## Build all images with 'dev' label and load to Docker
	IMAGE_LABEL=dev docker buildx bake all --load

clean: ## Clean build cache and rebuild from scratch
	docker buildx bake all --no-cache --load

# Utility targets
validate: ## Validate Docker Compose and Bake configurations
	docker compose config --quiet
	docker buildx bake --print all > /dev/null

push: ## Build and push all images to registry (don't load locally)
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