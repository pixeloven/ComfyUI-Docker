// Docker Bake configuration for ComfyUI-Docker
// Supports multiple runtimes with proper caching and GitHub Container Registry

// Variables with defaults
variable "REGISTRY_URL" {
    default = "ghcr.io/pixeloven/comfyui-docker/"
}

variable "IMAGE_LABEL" {
    default = "latest"
}

variable "VERSION" {
    default = "latest"
}

variable "RUNTIME" {
    default = "cuda"
}

variable "PLATFORMS" {
    default = ["linux/amd64"]
}

// Build arguments for better caching
variable "BUILDKIT_INLINE_CACHE" {
    default = "1"
}

variable "DOCKER_BUILDKIT" {
    default = "1"
}

// Cache configuration
variable "CACHE_TYPE" {
    default = "registry"  // gha, registry, or inline - registry works for both local and CI
}

variable "CACHE_MODE" {
    default = "max"  // max or min
}

target "runtime-cuda" {
    context = "services/runtime"
    dockerfile = "dockerfile.cuda.runtime"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}runtime:cuda-${IMAGE_LABEL}",
        "${REGISTRY_URL}runtime:cuda-v${VERSION}",
        "${REGISTRY_URL}runtime:cuda-cache"
    ]
    cache-from = [
        "type=${CACHE_TYPE},ref=${REGISTRY_URL}runtime:cuda-cache,optional=true",
        "type=gha,scope=runtime-cuda"
    ]
    cache-to = [
        "type=${CACHE_TYPE},ref=${REGISTRY_URL}runtime:cuda-cache,mode=${CACHE_MODE}",
        "type=gha,scope=runtime-cuda,mode=${CACHE_MODE}"
    ]
    args = {
        BUILDKIT_INLINE_CACHE = BUILDKIT_INLINE_CACHE
        DOCKER_BUILDKIT = DOCKER_BUILDKIT
    }
}

target "runtime-cpu" {
    context = "services/runtime"
    dockerfile = "dockerfile.cpu.runtime"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}runtime:cpu-${IMAGE_LABEL}",
        "${REGISTRY_URL}runtime:cpu-v${VERSION}",
        "${REGISTRY_URL}runtime:cpu-cache"
    ]
    cache-from = [
        "type=${CACHE_TYPE},ref=${REGISTRY_URL}runtime:cpu-cache,optional=true",
        "type=gha,scope=runtime-cpu"
    ]
    cache-to = [
        "type=${CACHE_TYPE},ref=${REGISTRY_URL}runtime:cpu-cache,mode=${CACHE_MODE}",
        "type=gha,scope=runtime-cpu,mode=${CACHE_MODE}"
    ]
    args = {
        BUILDKIT_INLINE_CACHE = BUILDKIT_INLINE_CACHE
        DOCKER_BUILDKIT = DOCKER_BUILDKIT
    }
}

target "sageattention-builder" {
    context = "services/builder/sageattention"
    dockerfile = "dockerfile.sageattention.builder"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}sageattention-builder:${IMAGE_LABEL}",
        "${REGISTRY_URL}sageattention-builder:v${VERSION}",
        "${REGISTRY_URL}sageattention-builder:cache"
    ]
    cache-from = [
        "type=${CACHE_TYPE},ref=${REGISTRY_URL}sageattention-builder:cache,optional=true",
        "type=gha,scope=sageattention-builder"
    ]
    cache-to = [
        "type=${CACHE_TYPE},ref=${REGISTRY_URL}sageattention-builder:cache,mode=${CACHE_MODE}",
        "type=gha,scope=sageattention-builder,mode=${CACHE_MODE}"
    ]
    target = "sageattention-builder"
    args = {
        BUILDKIT_INLINE_CACHE = BUILDKIT_INLINE_CACHE
        DOCKER_BUILDKIT = DOCKER_BUILDKIT
    }
}

target "core-cuda" {
    context = "services/comfy/core"
    contexts = {
        runtime = "target:runtime-cuda"
    }
    dockerfile = "dockerfile.comfy.core"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}core:cuda-${IMAGE_LABEL}",
        "${REGISTRY_URL}core:cuda-v${VERSION}",
        "${REGISTRY_URL}core:cuda-cache"
    ]
    cache-from = [
        "type=${CACHE_TYPE},ref=${REGISTRY_URL}runtime:cuda-cache,optional=true",
        "type=${CACHE_TYPE},ref=${REGISTRY_URL}core:cuda-cache,optional=true",
        "type=gha,scope=core-cuda"
    ]
    cache-to = [
        "type=${CACHE_TYPE},ref=${REGISTRY_URL}core:cuda-cache,mode=${CACHE_MODE}",
        "type=gha,scope=core-cuda,mode=${CACHE_MODE}"
    ]
    args = {
        RUNTIME = "cuda"
        BUILDKIT_INLINE_CACHE = BUILDKIT_INLINE_CACHE
        DOCKER_BUILDKIT = DOCKER_BUILDKIT
    }
    depends_on = ["runtime-cuda"]
}

target "core-cpu" {
    context = "services/comfy/core"
    contexts = {
        runtime = "target:runtime-cpu"
    }
    dockerfile = "dockerfile.comfy.core"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}core:cpu-${IMAGE_LABEL}",
        "${REGISTRY_URL}core:cpu-v${VERSION}",
        "${REGISTRY_URL}core:cpu-cache"
    ]
    cache-from = [
        "type=${CACHE_TYPE},ref=${REGISTRY_URL}runtime:cpu-cache,optional=true",
        "type=${CACHE_TYPE},ref=${REGISTRY_URL}core:cpu-cache,optional=true",
        "type=gha,scope=core-cpu"
    ]
    cache-to = [
        "type=${CACHE_TYPE},ref=${REGISTRY_URL}core:cpu-cache,mode=${CACHE_MODE}",
        "type=gha,scope=core-cpu,mode=${CACHE_MODE}"
    ]
    args = {
        RUNTIME = "cpu"
        BUILDKIT_INLINE_CACHE = BUILDKIT_INLINE_CACHE
        DOCKER_BUILDKIT = DOCKER_BUILDKIT
    }
    depends_on = ["runtime-cpu"]
}

target "complete-cuda" {
    context = "services/comfy/complete"
    contexts = {
        core = "target:core-cuda"
        sageattention-builder = "target:sageattention-builder"
    }
    dockerfile = "dockerfile.comfy.cuda.complete"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}complete:cuda-${IMAGE_LABEL}",
        "${REGISTRY_URL}complete:cuda-v${VERSION}",
        "${REGISTRY_URL}complete:cuda-cache"
    ]
    cache-from = [
        "type=${CACHE_TYPE},ref=${REGISTRY_URL}runtime:cuda-cache,optional=true",
        "type=${CACHE_TYPE},ref=${REGISTRY_URL}core:cuda-cache,optional=true",
        "type=${CACHE_TYPE},ref=${REGISTRY_URL}complete:cuda-cache,optional=true",
        "type=gha,scope=complete-cuda"
    ]
    cache-to = [
        "type=${CACHE_TYPE},ref=${REGISTRY_URL}complete:cuda-cache,mode=${CACHE_MODE}",
        "type=gha,scope=complete-cuda,mode=${CACHE_MODE}"
    ]
    depends_on = ["core-cuda", "sageattention-builder"]
    args = {
        BUILDKIT_INLINE_CACHE = BUILDKIT_INLINE_CACHE
        DOCKER_BUILDKIT = DOCKER_BUILDKIT
    }
}

// Convenience groups
group "default" {
    targets = ["all"]
}

group "all" {
    targets = ["runtime", "cuda", "cpu"]
}

group "core" {
    targets = ["runtime-cuda", "runtime-cpu", "core-cuda", "core-cpu"]
}

group "runtime" {
    targets = ["runtime-cuda", "runtime-cpu"]
}

group "cuda" {
    targets = ["runtime-cuda", "core-cuda", "complete-cuda"]
}

group "cpu" {
    targets = ["runtime-cpu", "core-cpu"]
}

group "builders" {
    targets = ["sageattention-builder"]
}

