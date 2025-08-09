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

target "runtime-cuda" {
    context = "services/runtime"
    dockerfile = "dockerfile.cuda.runtime"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}runtime:cuda-${IMAGE_LABEL}",
        "${REGISTRY_URL}runtime:cuda-v${VERSION}",
        "${REGISTRY_URL}runtime:cuda-cache"
    ]
    cache-from = ["type=registry,ref=${REGISTRY_URL}runtime:cuda-cache,optional=true"]
    cache-to   = ["type=inline"]
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
    cache-from = ["type=registry,ref=${REGISTRY_URL}runtime:cpu-cache,optional=true"]
    cache-to   = ["type=inline"]
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
    cache-from = ["type=registry,ref=${REGISTRY_URL}sageattention-builder:cache,optional=true"]
    cache-to   = ["type=inline"]
    target = "sageattention-builder"
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
        "type=registry,ref=${REGISTRY_URL}runtime:cuda-cache,optional=true",
        "type=registry,ref=${REGISTRY_URL}core:cuda-cache,optional=true"
    ]
    cache-to   = ["type=inline"]
    args = {
        RUNTIME = "cuda"
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
        "type=registry,ref=${REGISTRY_URL}runtime:cpu-cache,optional=true",
        "type=registry,ref=${REGISTRY_URL}core:cpu-cache,optional=true"
    ]
    cache-to   = ["type=inline"]
    args = {
        RUNTIME = "cpu"
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
        "type=registry,ref=${REGISTRY_URL}runtime:cuda-cache,optional=true",
        "type=registry,ref=${REGISTRY_URL}core:cuda-cache,optional=true",
        "type=registry,ref=${REGISTRY_URL}complete:cuda-cache,optional=true"
    ]
    cache-to   = ["type=inline"]
    depends_on = ["core-cuda", "sageattention-builder"]
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

