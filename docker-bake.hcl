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
        "${REGISTRY_URL}runtime-cuda:${IMAGE_LABEL}",
        "${REGISTRY_URL}runtime-cuda:cache"
    ]
    cache-from = ["type=registry,ref=${REGISTRY_URL}runtime-cuda:cache"]
    cache-to   = ["type=inline"]
}

target "runtime-cpu" {
    context = "services/runtime"
    dockerfile = "dockerfile.cpu.runtime"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}runtime-cpu:${IMAGE_LABEL}",
        "${REGISTRY_URL}runtime-cpu:cache"
    ]
    cache-from = ["type=registry,ref=${REGISTRY_URL}runtime-cpu:cache"]
    cache-to   = ["type=inline"]
}

target "comfy-cuda" {
    context = "services/comfy/base"
    contexts = {
        runtime = "target:runtime-cuda"
    }
    dockerfile = "dockerfile.comfy.base"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}comfy-cuda:${IMAGE_LABEL}",
        "${REGISTRY_URL}comfy-cuda:cache"
    ]
    cache-from = [
        "type=registry,ref=${REGISTRY_URL}runtime-cuda:cache",
        "type=registry,ref=${REGISTRY_URL}comfy-cuda:cache"
    ]
    cache-to   = ["type=inline"]
    args = {
        RUNTIME = "cuda"
    }
    depends_on = ["runtime-cuda"]
}

target "comfy-cpu" {
    context = "services/comfy/base"
    contexts = {
        runtime = "target:runtime-cpu"
    }
    dockerfile = "dockerfile.comfy.base"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}comfy-cpu:${IMAGE_LABEL}",
        "${REGISTRY_URL}comfy-cpu:cache"
    ]
    cache-from = [
        "type=registry,ref=${REGISTRY_URL}runtime-cpu:cache",
        "type=registry,ref=${REGISTRY_URL}comfy-cuda:cache"
    ]
    cache-to   = ["type=inline"]
    args = {
        RUNTIME = "cpu"
    }
    depends_on = ["runtime-cpu"]
}

target "comfy-cuda-extended" {
    context = "services/comfy/extended"
    contexts = {
        base = "target:comfy-cuda"
    }
    dockerfile = "dockerfile.comfy.cuda.extended"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}comfy-cuda-extended:${IMAGE_LABEL}",
        "${REGISTRY_URL}comfy-cuda-extended:cache"
    ]
    cache-from = [
        "type=registry,ref=${REGISTRY_URL}runtime-cuda:cache",
        "type=registry,ref=${REGISTRY_URL}comfy-cuda:cache",
        "type=registry,ref=${REGISTRY_URL}comfy-cuda-extended:cache"
    ]
    cache-to   = ["type=inline"]
    depends_on = ["comfy-cuda"]
}

// Convenience groups
group "default" {
    targets = ["all"]
}

group "all" {
    targets = ["runtime", "cuda", "cpu"]
}

group "base" {
    targets = ["runtime-cuda", "runtime-cpu", "comfy-cuda", "comfy-cpu"]
}

group "runtime" {
    targets = ["runtime-cuda", "runtime-cpu"]
}

group "cuda" {
    targets = ["runtime-cuda", "comfy-cuda", "comfy-cuda-extended"]
}

group "cpu" {
    targets = ["runtime-cpu", "comfy-cpu"]
}

