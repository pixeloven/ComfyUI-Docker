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
    dockerfile = "services/comfy/dockerfile.nvidia.runtime"
    platforms = var.PLATFORMS
    tags = [
        "${var.REGISTRY_URL}/comfyui-docker/runtime-nvidia:${var.IMAGE_LABEL}",
        "${var.REGISTRY_URL}/comfyui-docker/runtime-nvidia:latest"
    ]
    cache-from = ["type=registry,ref=${var.REGISTRY_URL}/comfyui-docker/runtime-nvidia:cache"]
    cache-to = ["type=registry,ref=${var.REGISTRY_URL}/comfyui-docker/runtime-nvidia:cache,mode=max"]
}

target "runtime-cpu" {
    context = "services/comfy"
    dockerfile = "services/comfy/dockerfile.cpu.runtime"
    platforms = var.PLATFORMS
    tags = [
        "${var.REGISTRY_URL}/comfyui-docker/runtime-cpu:${var.IMAGE_LABEL}",
        "${var.REGISTRY_URL}/comfyui-docker/runtime-cpu:latest"
    ]
    cache-from = ["type=registry,ref=${var.REGISTRY_URL}/comfyui-docker/runtime-cpu:cache"]
    cache-to = ["type=registry,ref=${var.REGISTRY_URL}/comfyui-docker/runtime-cpu:cache,mode=max"]
}

target "comfy-nvidia" {
    context = "services/comfy"
    dockerfile = "services/comfy/dockerfile.comfy.base"
    platforms = var.PLATFORMS
    tags = [
        "${var.REGISTRY_URL}/comfyui-docker/comfy:${var.IMAGE_LABEL}",
        "${var.REGISTRY_URL}/comfyui-docker/comfy:latest",
        "${var.REGISTRY_URL}/comfyui-docker/comfy:nvidia-${var.IMAGE_LABEL}"
    ]
    cache-from = [
        "type=registry,ref=${var.REGISTRY_URL}/comfyui-docker/runtime-nvidia:cache",
        "type=registry,ref=${var.REGISTRY_URL}/comfyui-docker/comfy:cache"
    ]
    cache-to = ["type=registry,ref=${var.REGISTRY_URL}/comfyui-docker/comfy:cache,mode=max"]
    args = {
        RUNTIME = "nvidia"
    }
}

target "comfy-cpu" {
    context = "services/comfy"
    dockerfile = "services/comfy/dockerfile.comfy.base"
    platforms = var.PLATFORMS
    tags = [
        "${var.REGISTRY_URL}/comfyui-docker/comfy-cpu:${var.IMAGE_LABEL}",
        "${var.REGISTRY_URL}/comfyui-docker/comfy-cpu:latest"
    ]
    cache-from = [
        "type=registry,ref=${var.REGISTRY_URL}/comfyui-docker/runtime-cpu:cache",
        "type=registry,ref=${var.REGISTRY_URL}/comfyui-docker/comfy-cpu:cache"
    ]
    cache-to = ["type=registry,ref=${var.REGISTRY_URL}/comfyui-docker/comfy-cpu:cache,mode=max"]
    args = {
        RUNTIME = "cpu"
    }
}

// ComfyUI setup image
target "comfy-setup" {
    context = "services/comfy-setup"
    dockerfile = "services/comfy-setup/Dockerfile"
    platforms = var.PLATFORMS
    tags = [
        "${var.REGISTRY_URL}/comfyui-docker/comfy-setup:${var.IMAGE_LABEL}",
        "${var.REGISTRY_URL}/comfyui-docker/comfy-setup:latest"
    ]
    cache-from = ["type=registry,ref=${var.REGISTRY_URL}/comfyui-docker/comfy-setup:cache"]
    cache-to = ["type=registry,ref=${var.REGISTRY_URL}/comfyui-docker/comfy-setup:cache,mode=max"]
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

