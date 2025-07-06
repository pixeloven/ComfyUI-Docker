// Docker Bake configuration for ComfyUI-Docker
// Supports multiple runtimes with proper caching and GitHub Container Registry

// Variables with defaults
variable "REGISTRY_URL" {
    default = "ghcr.io/pixeloven"
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
    context = "services/comfy"
    dockerfile = "dockerfile.nvidia.runtime"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}/comfyui-docker/runtime-nvidia:${IMAGE_LABEL}"
    ]
    cache-from = ["type=registry,ref=${REGISTRY_URL}/comfyui-docker/runtime-nvidia:cache"]
    cache-to   = ["type=inline"]
}

target "runtime-cpu" {
    context = "services/comfy"
    dockerfile = "dockerfile.cpu.runtime"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}/comfyui-docker/runtime-cpu:${IMAGE_LABEL}"
    ]
    cache-from = ["type=registry,ref=${REGISTRY_URL}/comfyui-docker/runtime-cpu:cache"]
    cache-to   = ["type=inline"]
}

target "comfy-nvidia" {
    context = "services/comfy"
    dockerfile = "dockerfile.comfy.base"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}/comfyui-docker/comfy-nvidia:${IMAGE_LABEL}"
    ]
    cache-from = [
        "type=registry,ref=${REGISTRY_URL}/comfyui-docker/runtime-nvidia:cache",
        "type=registry,ref=${REGISTRY_URL}/comfyui-docker/comfy-nvidia:cache"
    ]
    cache-to   = ["type=inline"]
    args = {
        RUNTIME = "nvidia"
    }
}

target "comfy-cpu" {
    context = "services/comfy"
    dockerfile = "dockerfile.comfy.base"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}/comfyui-docker/comfy-cpu:${IMAGE_LABEL}"
    ]
    cache-from = [
        "type=registry,ref=${REGISTRY_URL}/comfyui-docker/runtime-cpu:cache",
        "type=registry,ref=${REGISTRY_URL}/comfyui-docker/comfy-cpu:cache"
    ]
    cache-to   = ["type=inline"]
    args = {
        RUNTIME = "cpu"
    }
}

// ComfyUI setup image
target "comfy-setup" {
    context = "services/comfy-setup"
    dockerfile = "Dockerfile"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}/comfyui-docker/comfy-setup:${IMAGE_LABEL}"
    ]
    cache-from = ["type=registry,ref=${REGISTRY_URL}/comfyui-docker/comfy-setup:cache"]
    cache-to   = ["type=inline"]
}

// Convenience groups
group "all" {
    targets = ["runtime", "comfy", "comfy-setup"]
}

// Base runtime images
group "runtime" {
    targets = ["runtime-nvidia", "runtime-cpu"]
}

group "nvidia" {
    targets = ["runtime-nvidia", "comfy-nvidia"]
}

group "cpu" {
    targets = ["runtime-cpu", "comfy-cpu"]
}

group "comfy" {
    targets = ["comfy-nvidia", "comfy-cpu"]
}

