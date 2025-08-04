// Docker Bake configuration for ComfyUI-Docker
// Supports multiple runtimes with proper caching and GitHub Container Registry

// Variables with defaults
variable "REGISTRY_URL" {
    default = "ghcr.io/pixeloven/comfyui-docker/"
}

variable "IMAGE_LABEL" {
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
        "${REGISTRY_URL}runtime:cuda-cache"
    ]
    cache-from = ["type=registry,ref=${REGISTRY_URL}runtime:cuda-cache"]
    cache-to   = ["type=inline"]
}

target "runtime-cpu" {
    context = "services/runtime"
    dockerfile = "dockerfile.cpu.runtime"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}runtime:cpu-${IMAGE_LABEL}",
        "${REGISTRY_URL}runtime:cpu-cache"
    ]
    cache-from = ["type=registry,ref=${REGISTRY_URL}runtime:cpu-cache"]
    cache-to   = ["type=inline"]
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
        "${REGISTRY_URL}core:cuda-cache"
    ]
    cache-from = [
        "type=registry,ref=${REGISTRY_URL}runtime:cuda-cache",
        "type=registry,ref=${REGISTRY_URL}core:cuda-cache"
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
        "${REGISTRY_URL}core:cpu-cache"
    ]
    cache-from = [
        "type=registry,ref=${REGISTRY_URL}runtime:cpu-cache",
        "type=registry,ref=${REGISTRY_URL}core:cuda-cache"
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
    }
    dockerfile = "dockerfile.comfy.cuda.complete"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}complete:cuda-${IMAGE_LABEL}",
        "${REGISTRY_URL}complete:cuda-cache"
    ]
    cache-from = [
        "type=registry,ref=${REGISTRY_URL}runtime:cuda-cache",
        "type=registry,ref=${REGISTRY_URL}core:cuda-cache",
        "type=registry,ref=${REGISTRY_URL}complete:cuda-cache"
    ]
    cache-to   = ["type=inline"]
    depends_on = ["core-cuda"]
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

