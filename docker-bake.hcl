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
    default = "nvidia"
}

variable "PLATFORMS" {
    default = ["linux/amd64"]
}

target "runtime-nvidia" {
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

target "comfy-nvidia" {
    context = "services/comfy/base"
    contexts = {
        runtime = "target:runtime-nvidia"
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
        RUNTIME = "nvidia"
    }
    depends_on = ["runtime-nvidia"]
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
        "type=registry,ref=${REGISTRY_URL}comfy-cpu:cache"
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
        base = "target:comfy-nvidia"
    }
    dockerfile = "dockerfile.comfy.cuda.extended"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}comfy-cuda-extended:${IMAGE_LABEL}",
        "${REGISTRY_URL}comfy-cuda-extended:cache"
    ]
    cache-from = [
        "type=registry,ref=${REGISTRY_URL}runtime-cuda:cache",
        "type=registry,ref=${REGISTRY_URL}comfy-cuda:cache"
    ]
    cache-to   = ["type=inline"]
    depends_on = ["comfy-nvidia"]
}

// Convenience groups
group "default" {
    targets = ["all"]
}

group "all" {
    targets = ["runtime", "nvidia", "cpu"]
}

group "runtime" {
    targets = ["runtime-nvidia", "runtime-cpu"]
}

group "nvidia" {
    targets = ["runtime-nvidia", "comfy-nvidia", "comfy-cuda-extended"]
}

group "cpu" {
    targets = ["runtime-cpu", "comfy-cpu"]
}


