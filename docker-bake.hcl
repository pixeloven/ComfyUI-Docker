// Docker Bake configuration for ComfyUI-Docker
// Supports multiple runtimes with proper caching and GitHub Container Registry

// Variables with defaults
variable "REPOSITORY_OWNER" {
    default = "pixeloven"
}

variable "REGISTRY_URL" {
    default = "ghcr.io/${REPOSITORY_OWNER}/comfyui/"
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

variable "COMFYUI_VERSION" {
    // Repository builds pin a stable upstream source tag by default. Scheduled
    // publishing resolves the latest upstream release and overrides this.
    // Set to "master" explicitly for a nightly build.
    default = "v0.33.1"
}

variable "PUBLISH_LATEST" {
    // CI sets this only for stable publishing. A nightly/custom IMAGE_LABEL
    // must never move the stable *-latest tags.
    default = false
}

target "runtime-cuda" {
    context = "services/runtime"
    dockerfile = "dockerfile.cuda.runtime"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}runtime:cuda-${IMAGE_LABEL}",
        "${REGISTRY_URL}runtime:cuda-cache",
        PUBLISH_LATEST ? "${REGISTRY_URL}runtime:cuda-latest" : ""
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
        "${REGISTRY_URL}runtime:cpu-cache",
        PUBLISH_LATEST ? "${REGISTRY_URL}runtime:cpu-latest" : ""
    ]
    cache-from = ["type=registry,ref=${REGISTRY_URL}runtime:cpu-cache,optional=true"]
    cache-to   = ["type=inline"]
}

target "runtime-rocm" {
    context = "services/runtime"
    dockerfile = "dockerfile.cpu.runtime"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}runtime:rocm-${IMAGE_LABEL}",
        "${REGISTRY_URL}runtime:rocm-cache",
        PUBLISH_LATEST ? "${REGISTRY_URL}runtime:rocm-latest" : ""
    ]
    cache-from = ["type=registry,ref=${REGISTRY_URL}runtime:rocm-cache,optional=true"]
    cache-to   = ["type=inline"]
}

target "runtime-xpu" {
    context = "services/runtime"
    dockerfile = "dockerfile.cpu.runtime"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}runtime:xpu-${IMAGE_LABEL}",
        "${REGISTRY_URL}runtime:xpu-cache",
        PUBLISH_LATEST ? "${REGISTRY_URL}runtime:xpu-latest" : ""
    ]
    cache-from = ["type=registry,ref=${REGISTRY_URL}runtime:xpu-cache,optional=true"]
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
        "${REGISTRY_URL}core:cuda-${COMFYUI_VERSION}",
        "${REGISTRY_URL}core:cuda-cache",
        PUBLISH_LATEST ? "${REGISTRY_URL}core:cuda-latest" : ""
    ]
    cache-from = [
        "type=registry,ref=${REGISTRY_URL}runtime:cuda-cache,optional=true",
        "type=registry,ref=${REGISTRY_URL}core:cuda-cache,optional=true"
    ]
    cache-to   = ["type=inline"]
    args = {
        RUNTIME = "cuda"
        TORCH_INDEX = "cu130"
        COMFYUI_VERSION = COMFYUI_VERSION
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
        "${REGISTRY_URL}core:cpu-${COMFYUI_VERSION}",
        "${REGISTRY_URL}core:cpu-cache",
        PUBLISH_LATEST ? "${REGISTRY_URL}core:cpu-latest" : ""
    ]
    cache-from = [
        "type=registry,ref=${REGISTRY_URL}runtime:cpu-cache,optional=true",
        "type=registry,ref=${REGISTRY_URL}core:cpu-cache,optional=true"
    ]
    cache-to   = ["type=inline"]
    args = {
        RUNTIME = "cpu"
        TORCH_INDEX = "cpu"
        COMFYUI_VERSION = COMFYUI_VERSION
    }
    depends_on = ["runtime-cpu"]
}

target "core-rocm" {
    context = "services/comfy/core"
    contexts = {
        runtime = "target:runtime-rocm"
    }
    dockerfile = "dockerfile.comfy.core"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}core:rocm-${IMAGE_LABEL}",
        "${REGISTRY_URL}core:rocm-${COMFYUI_VERSION}",
        "${REGISTRY_URL}core:rocm-cache",
        PUBLISH_LATEST ? "${REGISTRY_URL}core:rocm-latest" : ""
    ]
    cache-from = [
        "type=registry,ref=${REGISTRY_URL}runtime:rocm-cache,optional=true",
        "type=registry,ref=${REGISTRY_URL}core:rocm-cache,optional=true"
    ]
    cache-to = ["type=inline"]
    args = {
        RUNTIME = "rocm"
        TORCH_INDEX = "rocm7.2"
        COMFYUI_VERSION = COMFYUI_VERSION
    }
    depends_on = ["runtime-rocm"]
}

target "core-xpu" {
    context = "services/comfy/core"
    contexts = {
        runtime = "target:runtime-xpu"
    }
    dockerfile = "dockerfile.comfy.core"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}core:xpu-${IMAGE_LABEL}",
        "${REGISTRY_URL}core:xpu-${COMFYUI_VERSION}",
        "${REGISTRY_URL}core:xpu-cache",
        PUBLISH_LATEST ? "${REGISTRY_URL}core:xpu-latest" : ""
    ]
    cache-from = [
        "type=registry,ref=${REGISTRY_URL}runtime:xpu-cache,optional=true",
        "type=registry,ref=${REGISTRY_URL}core:xpu-cache,optional=true"
    ]
    cache-to = ["type=inline"]
    args = {
        RUNTIME = "xpu"
        TORCH_INDEX = "xpu"
        COMFYUI_VERSION = COMFYUI_VERSION
    }
    depends_on = ["runtime-xpu"]
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
        "${REGISTRY_URL}complete:cuda-${COMFYUI_VERSION}",
        "${REGISTRY_URL}complete:cuda-cache",
        PUBLISH_LATEST ? "${REGISTRY_URL}complete:cuda-latest" : ""
    ]
    cache-from = [
        "type=registry,ref=${REGISTRY_URL}runtime:cuda-cache,optional=true",
        "type=registry,ref=${REGISTRY_URL}core:cuda-cache,optional=true",
        "type=registry,ref=${REGISTRY_URL}complete:cuda-cache,optional=true"
    ]
    cache-to   = ["type=inline"]
    depends_on = ["core-cuda"]
}

target "mcp" {
    context = "services/mcp"
    dockerfile = "dockerfile.comfy.mcp"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}mcp:${IMAGE_LABEL}",
        "${REGISTRY_URL}mcp:cache",
        PUBLISH_LATEST ? "${REGISTRY_URL}mcp:latest" : ""
    ]
    cache-from = ["type=registry,ref=${REGISTRY_URL}mcp:cache,optional=true"]
    cache-to   = ["type=inline"]
    args = {
        MCP_VERSION = "v1.1.1"
    }
}

group "mcp" {
    targets = ["mcp"]
}

// Convenience groups
group "default" {
    targets = ["all"]
}

group "all" {
    targets = ["runtime", "cuda", "cpu", "rocm", "xpu", "mcp"]
}

group "core" {
    targets = ["runtime-cuda", "runtime-cpu", "runtime-rocm", "runtime-xpu", "core-cuda", "core-cpu", "core-rocm", "core-xpu"]
}

group "runtime" {
    targets = ["runtime-cuda", "runtime-cpu", "runtime-rocm", "runtime-xpu"]
}

group "cuda" {
    targets = ["runtime-cuda", "core-cuda", "complete-cuda"]
}

group "cpu" {
    targets = ["runtime-cpu", "core-cpu"]
}

group "rocm" {
    targets = ["runtime-rocm", "core-rocm"]
}

group "xpu" {
    targets = ["runtime-xpu", "core-xpu"]
}
