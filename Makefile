# ComfyUI-Docker Makefile
# Provides convenient targets for local development and building

.PHONY: help all runtime core cuda cpu rocm xpu clean smoke

# Default target
help: ## Show this help message
	@echo "ComfyUI-Docker Build Targets:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

# Build all images
all: ## Build all images (runtime + core + complete) and load to Docker
	docker buildx bake all --load

# Runtime images
runtime: ## Build all runtime images (CUDA, CPU, ROCm, XPU) and load to Docker
	docker buildx bake runtime --load

runtime-cuda: ## Build CUDA runtime image and load to Docker
	docker buildx bake runtime-cuda --load

runtime-cpu: ## Build CPU runtime image and load to Docker
	docker buildx bake runtime-cpu --load

# Core images 
core: ## Build core images (runtime + core layers for CUDA, CPU, ROCm, XPU) and load to Docker
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

rocm: ## Build AMD ROCm stack and load to Docker
	docker buildx bake rocm --load

xpu: ## Build Intel XPU stack and load to Docker
	docker buildx bake xpu --load

# Complete images
complete-cuda: ## Build CUDA complete image and load to Docker
	docker buildx bake complete-cuda --load

# Development targets
dev: ## Build all images with 'dev' label and load to Docker
	IMAGE_LABEL=dev docker buildx bake all --load

clean: ## Clean build cache and rebuild from scratch
	docker buildx bake all --no-cache --load

# Utility targets
# Pinned by tag and digest, like CI's validate-examples step. KUBERNETES_VERSION
# is the schema version the example is checked against.
KUBECONFORM ?= docker run --rm -v "$(CURDIR)":/repo:ro -w /repo ghcr.io/yannh/kubeconform:v0.8.0@sha256:faffaf43f95aa6425306e1ab8d6fcad72acb9049158f38e574c085ea1ec0f64e
KUBERNETES_VERSION ?= 1.36.4

validate: ## Validate Bake, example Compose configurations and the Kubernetes example
	docker buildx bake --print all > /dev/null
	cd examples/core-gpu && docker compose config --quiet
	cd examples/complete-gpu && docker compose config --quiet
	cd examples/core-cpu && docker compose config --quiet
	cd examples/core-amd && docker compose config --quiet
	cd examples/core-intel && docker compose config --quiet
	$(KUBECONFORM) -strict -summary -kubernetes-version $(KUBERNETES_VERSION) examples/kubernetes

# Boot smoke test, the same script CI's smoke-cpu job runs, on core-cpu built
# from this tree under the never-published `smoke` label, as CI builds it.
# SMOKE_NETWORK=host on a host without a docker0 bridge (build and run).
# Node classes are compared against SMOKE_BASELINE, pulled from GHCR (main's
# latest build by default); SMOKE_BASELINE= skips the comparison.
SMOKE_NETWORK ?=
SMOKE_BASELINE ?= ghcr.io/pixeloven/comfyui/core:cpu-latest

smoke: ## Build core-cpu from this tree, boot it as PUID/PGID 1001, check readiness, volume ownership and nodes vs main
	IMAGE_LABEL=smoke docker buildx bake core-cpu --load $(if $(filter host,$(SMOKE_NETWORK)),--set "*.network=host" --allow network.host)
	tests/smoke/run.sh $(if $(SMOKE_NETWORK),--network $(SMOKE_NETWORK)) $(if $(SMOKE_BASELINE),--baseline $(SMOKE_BASELINE)) ghcr.io/pixeloven/comfyui/core:cpu-smoke

push: ## Build and push all images to registry (don't load locally)
	docker buildx bake all --push

# Local testing (uses example directories)
test: ## Start core-gpu example locally for testing
	cd examples/core-gpu && docker compose up -d

test-cpu: ## Start core-cpu example locally for testing
	cd examples/core-cpu && docker compose up -d

test-complete: ## Start complete-gpu example locally for testing
	cd examples/complete-gpu && docker compose up -d

test-amd: ## Start the AMD ROCm example locally for testing
	cd examples/core-amd && docker compose up -d

test-intel: ## Start the Intel XPU example locally for testing
	cd examples/core-intel && docker compose up -d

stop: ## Stop all example services
	-cd examples/core-gpu && docker compose down
	-cd examples/complete-gpu && docker compose down
	-cd examples/core-cpu && docker compose down
	-cd examples/core-amd && docker compose down
	-cd examples/core-intel && docker compose down

logs: ## Show logs from core-gpu example
	cd examples/core-gpu && docker compose logs -f
