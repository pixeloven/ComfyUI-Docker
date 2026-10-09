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
    // THE PIN: which ComfyUI goes inside the images. This file is the single
    // source of truth, and bumping it is a deliberate, reviewable commit --
    // the images change, so our own VERSION should move with it.
    //
    // CI used to resolve this from Comfy-Org/ComfyUI releases/latest at build
    // time, which meant a release was not reproducible: v0.1.0 baked whatever
    // upstream happened to have shipped by the minute the tag ran, a rebuild
    // would bake something else, and a local build used the default here --
    // three different meanings for one tag.
    //
    // Tracking upstream is what the NIGHTLY is for: it resolves master, passes
    // the resolved COMMIT here, and publishes under `*-nightly` alone.
    //
    // This value is no longer a TAG on the published image. It was, and that
    // made an unreviewed cron the author of the `cuda-v0.36.0` line while a
    // reviewed release published `cuda-2.0.0` containing v0.34.0 -- two
    // identities for one artifact, disagreeing. What is inside an image is now
    // stated once, by org.opencontainers.image.version, which the Dockerfile
    // sets from this and which is true for a commit as well as a tag.
    default = "v0.38.0"
}

variable "COMFY_DOCS_SHA" {
    // The Comfy-Org/docs commit the mcp image (comfyrelay) indexes for docs_search
    // (#134): the source of docs.comfy.org, GPL-3.0, recorded in the image's
    // NOTICE and in the index. The repo has no tags, so it is pinned by full
    // commit SHA and bumped by PR, like any supply-chain pin. It tracks the
    // latest ComfyUI, not COMFYUI_VERSION, and docs_search says so.
    //
    // A bump must name a commit on Comfy-Org/docs `main` (an ancestor of its
    // tip): GitHub serves any commit in the repo's fork network by SHA, so a
    // SHA from someone's fork would fetch just as well. Check it with the
    // compare API: gh api repos/Comfy-Org/docs/compare/<sha>...main reports
    // "ahead" or "identical" for a commit on main. CI's docs-pin job runs
    // that check on every PR that changes this file.
    default = "efb8fdd3de17027da633eb9c12e80fbbeb993a19"
}

variable "GIT_SHA" {
    // The commit being built. The mcp image's NOTICE (its Corresponding
    // Source pointer) and its guides' URLs name it, so an image built between
    // releases points at the files it was built from (#136). CI passes it;
    // without it they point at the release tag of the version the image reports.
    default = ""
}

variable "IMAGE_VERSION" {
    // OUR packaging version for the ComfyUI image family, from the VERSION file.
    // Distinct from COMFYUI_VERSION, which is what is INSIDE the image -- the
    // Helm `version` vs `appVersion` split. Changing a Dockerfile without
    // changing ComfyUI otherwise overwrites `cuda-v0.33.1` with different bytes,
    // which is the mutable-tag problem the whole lockfile effort exists to
    // avoid. Empty on ordinary pushes; set by a release tag.
    default = ""
}

variable "COMFYCTL_VERSION" {
    // Semver for the comfyctl image, set only by a release tag. Empty on ordinary
    // pushes, which publish the commit-sha and :latest tags alone.
    default = ""
}

variable "PUBLISH_LATEST" {
    // CI sets this only for stable publishing. A nightly/custom IMAGE_LABEL
    // must never move the stable *-latest tags.
    default = false
}

variable "SAGEATTENTION_RELEASE_URL" {
    // Release produced from thu-ml/SageAttention v2.2.0 for the Python,
    // PyTorch, and CUDA ABI used by the current CUDA image. NOT immutable --
    // that release can be re-uploaded in place, which is why every wheel below
    // is pinned by URL *and* checked against a recorded sha256.
    default = "https://github.com/pixeloven/SageAttention-Wheels/releases/download/sageattention-v2.2.0-cu130-torch2.13.0"
}

target "runtime-cuda" {
    context = "services/runtime"
    dockerfile = "dockerfile.cuda.runtime"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}runtime:cuda-${IMAGE_LABEL}",
        "${REGISTRY_URL}runtime:cuda-cache",
        PUBLISH_LATEST ? "${REGISTRY_URL}runtime:cuda-latest" : "",
        IMAGE_VERSION != "" ? "${REGISTRY_URL}runtime:cuda-${IMAGE_VERSION}" : ""
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
        PUBLISH_LATEST ? "${REGISTRY_URL}runtime:cpu-latest" : "",
        IMAGE_VERSION != "" ? "${REGISTRY_URL}runtime:cpu-${IMAGE_VERSION}" : ""
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
        PUBLISH_LATEST ? "${REGISTRY_URL}runtime:rocm-latest" : "",
        IMAGE_VERSION != "" ? "${REGISTRY_URL}runtime:rocm-${IMAGE_VERSION}" : ""
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
        PUBLISH_LATEST ? "${REGISTRY_URL}runtime:xpu-latest" : "",
        IMAGE_VERSION != "" ? "${REGISTRY_URL}runtime:xpu-${IMAGE_VERSION}" : ""
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
        "${REGISTRY_URL}core:cuda-cache",
        PUBLISH_LATEST ? "${REGISTRY_URL}core:cuda-latest" : "",
        IMAGE_VERSION != "" ? "${REGISTRY_URL}core:cuda-${IMAGE_VERSION}" : ""
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
        "${REGISTRY_URL}core:cpu-cache",
        PUBLISH_LATEST ? "${REGISTRY_URL}core:cpu-latest" : "",
        IMAGE_VERSION != "" ? "${REGISTRY_URL}core:cpu-${IMAGE_VERSION}" : ""
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
        "${REGISTRY_URL}core:rocm-cache",
        PUBLISH_LATEST ? "${REGISTRY_URL}core:rocm-latest" : "",
        IMAGE_VERSION != "" ? "${REGISTRY_URL}core:rocm-${IMAGE_VERSION}" : ""
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
        "${REGISTRY_URL}core:xpu-cache",
        PUBLISH_LATEST ? "${REGISTRY_URL}core:xpu-latest" : "",
        IMAGE_VERSION != "" ? "${REGISTRY_URL}core:xpu-${IMAGE_VERSION}" : ""
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
        "${REGISTRY_URL}complete:cuda-cache",
        PUBLISH_LATEST ? "${REGISTRY_URL}complete:cuda-latest" : "",
        IMAGE_VERSION != "" ? "${REGISTRY_URL}complete:cuda-${IMAGE_VERSION}" : ""
    ]
    cache-from = [
        "type=registry,ref=${REGISTRY_URL}runtime:cuda-cache,optional=true",
        "type=registry,ref=${REGISTRY_URL}core:cuda-cache,optional=true",
        "type=registry,ref=${REGISTRY_URL}complete:cuda-cache,optional=true"
    ]
    cache-to   = ["type=inline"]
    depends_on = ["core-cuda"]
}

// SageAttention wheels contain native kernels for one NVIDIA compute
// capability. Keep the generic complete image portable and publish explicit,
// immutable variants so a deployment can select the architecture it runs on.
target "complete-cuda-sm80" {
    inherits = ["complete-cuda"]
    tags = [
        "${REGISTRY_URL}complete:cuda-sm80-${IMAGE_LABEL}",
        PUBLISH_LATEST ? "${REGISTRY_URL}complete:cuda-sm80-latest" : "",
        IMAGE_VERSION != "" ? "${REGISTRY_URL}complete:cuda-sm80-${IMAGE_VERSION}" : ""
    ]
    args = {
        SAGEATTENTION_ARCH = "sm80"
        SAGEATTENTION_WHEEL_URL = "${SAGEATTENTION_RELEASE_URL}/sageattention-2.2.0+cu130.torch2.13.0.sm80-cp312-cp312-linux_x86_64.whl"
        SAGEATTENTION_WHEEL_SHA256 = "a0273034509e3ef909fcd6a60557e594899f5e1fcb3af2146cbf84dceeedeb2a"
    }
}

target "complete-cuda-sm86" {
    inherits = ["complete-cuda"]
    tags = [
        "${REGISTRY_URL}complete:cuda-sm86-${IMAGE_LABEL}",
        PUBLISH_LATEST ? "${REGISTRY_URL}complete:cuda-sm86-latest" : "",
        IMAGE_VERSION != "" ? "${REGISTRY_URL}complete:cuda-sm86-${IMAGE_VERSION}" : ""
    ]
    args = {
        SAGEATTENTION_ARCH = "sm86"
        SAGEATTENTION_WHEEL_URL = "${SAGEATTENTION_RELEASE_URL}/sageattention-2.2.0+cu130.torch2.13.0.sm86-cp312-cp312-linux_x86_64.whl"
        SAGEATTENTION_WHEEL_SHA256 = "057130f7b64ab2ee87e01b222e95faac84bcb355c4b1f6309550b7aa91b32086"
    }
}

target "complete-cuda-sm89" {
    inherits = ["complete-cuda"]
    tags = [
        "${REGISTRY_URL}complete:cuda-sm89-${IMAGE_LABEL}",
        PUBLISH_LATEST ? "${REGISTRY_URL}complete:cuda-sm89-latest" : "",
        IMAGE_VERSION != "" ? "${REGISTRY_URL}complete:cuda-sm89-${IMAGE_VERSION}" : ""
    ]
    args = {
        SAGEATTENTION_ARCH = "sm89"
        SAGEATTENTION_WHEEL_URL = "${SAGEATTENTION_RELEASE_URL}/sageattention-2.2.0+cu130.torch2.13.0.sm89-cp312-cp312-linux_x86_64.whl"
        SAGEATTENTION_WHEEL_SHA256 = "ec903e7cb330aa26719a9a2459450ffc94e9079719f4989aa193486ef9177bba"
    }
}

target "complete-cuda-sm90" {
    inherits = ["complete-cuda"]
    tags = [
        "${REGISTRY_URL}complete:cuda-sm90-${IMAGE_LABEL}",
        PUBLISH_LATEST ? "${REGISTRY_URL}complete:cuda-sm90-latest" : "",
        IMAGE_VERSION != "" ? "${REGISTRY_URL}complete:cuda-sm90-${IMAGE_VERSION}" : ""
    ]
    args = {
        SAGEATTENTION_ARCH = "sm90"
        SAGEATTENTION_WHEEL_URL = "${SAGEATTENTION_RELEASE_URL}/sageattention-2.2.0+cu130.torch2.13.0.sm90-cp312-cp312-linux_x86_64.whl"
        SAGEATTENTION_WHEEL_SHA256 = "31ec9edf793c69f280b5d0f657e05fdfc35539473d9ee6b840f3a3adf3f4eaa2"
    }
}

target "complete-cuda-sm120" {
    inherits = ["complete-cuda"]
    tags = [
        "${REGISTRY_URL}complete:cuda-sm120-${IMAGE_LABEL}",
        PUBLISH_LATEST ? "${REGISTRY_URL}complete:cuda-sm120-latest" : "",
        IMAGE_VERSION != "" ? "${REGISTRY_URL}complete:cuda-sm120-${IMAGE_VERSION}" : ""
    ]
    args = {
        SAGEATTENTION_ARCH = "sm120"
        SAGEATTENTION_WHEEL_URL = "${SAGEATTENTION_RELEASE_URL}/sageattention-2.2.0+cu130.torch2.13.0.sm120-cp312-cp312-linux_x86_64.whl"
        SAGEATTENTION_WHEEL_SHA256 = "cd91503f88aafddcab0cd8603c61920e221ed4e7b4cfd3610bf063eeb5ce7acb"
    }
}

// The MCP sidecar for agents: comfyrelay (#103), the first-party server, since
// 5.0.0 (#136). Before that this image packaged artokun/comfyui-mcp.
// The context is the uv workspace root, so the image installs services/uv.lock.
// The guides the docs index covers (skills/comfyui-workflows/, #134) come in
// as the `skills` named context, since skills/ is outside that root.
target "mcp" {
    context = "services"
    dockerfile = "comfyrelay/dockerfile.comfy.relay"
    contexts = {
        skills = "skills"
    }
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}mcp:${IMAGE_LABEL}",
        "${REGISTRY_URL}mcp:cache",
        PUBLISH_LATEST ? "${REGISTRY_URL}mcp:latest" : "",
        IMAGE_VERSION != "" ? "${REGISTRY_URL}mcp:${IMAGE_VERSION}" : ""
    ]
    cache-from = ["type=registry,ref=${REGISTRY_URL}mcp:cache,optional=true"]
    cache-to   = ["type=inline"]
    args = {
        COMFYUI_VERSION = COMFYUI_VERSION
        COMFY_DOCS_SHA = COMFY_DOCS_SHA
        GIT_SHA = GIT_SHA
    }
}

group "mcp" {
    targets = ["mcp"]
}

// A stamp that changes weekly (the month, and the week of it), which invalidates
// mcp-convert's cached apt layer so its unpinned Debian packages are reinstalled,
// with their security fixes, at least once a week. Set it to force a refresh.
variable "APT_REFRESH" {
    default = ""
}

// The same server with a headless Chromium, so it converts UI-format workflows
// through ComfyUI's own frontend (#167). From the same Dockerfile with
// RELAY_CONVERT=1, and conversion is on by default in it. A separate image so
// the mcp image stays without a browser. The Playwright version, the Chromium
// build and the apt packages it adds are pinned in the Dockerfile.
target "mcp-convert" {
    inherits = ["mcp"]
    tags = [
        "${REGISTRY_URL}mcp-convert:${IMAGE_LABEL}",
        "${REGISTRY_URL}mcp-convert:cache",
        PUBLISH_LATEST ? "${REGISTRY_URL}mcp-convert:latest" : "",
        IMAGE_VERSION != "" ? "${REGISTRY_URL}mcp-convert:${IMAGE_VERSION}" : ""
    ]
    cache-from = ["type=registry,ref=${REGISTRY_URL}mcp-convert:cache,optional=true"]
    args = {
        RELAY_CONVERT = "1"
        APT_REFRESH = APT_REFRESH != "" ? APT_REFRESH : "${formatdate("YYYY-MM", timestamp())}-w${floor((parseint(formatdate("D", timestamp()), 10) - 1) / 7)}"
    }
}

// The comfyctl CLI as an image, whose `fetch` group is the model fetcher. It
// replaced the `fetch` image in 6.0.0 (#197). Independent of RUNTIME: it moves
// bytes and checks hashes, so there is no CUDA/CPU/ROCm variant to build. The
// context is the uv workspace root, so the image installs services/uv.lock (#177).
target "comfyctl" {
    context = "services"
    dockerfile = "comfyctl/dockerfile.comfy.ctl"
    platforms = PLATFORMS
    tags = [
        "${REGISTRY_URL}comfyctl:${IMAGE_LABEL}",
        "${REGISTRY_URL}comfyctl:cache",
        PUBLISH_LATEST ? "${REGISTRY_URL}comfyctl:latest" : "",
        // Consumers pin by DIGEST; these say whether a digest change was a
        // patch or a break, which a sha tag cannot.
        COMFYCTL_VERSION != "" ? "${REGISTRY_URL}comfyctl:${COMFYCTL_VERSION}" : "",
        COMFYCTL_VERSION != "" ? "${REGISTRY_URL}comfyctl:${regex_replace(COMFYCTL_VERSION, "\\.[0-9]+$", "")}" : ""
    ]
    cache-from = ["type=registry,ref=${REGISTRY_URL}comfyctl:cache,optional=true"]
    cache-to   = ["type=inline"]
}

group "comfyctl" {
    targets = ["comfyctl"]
}

// Convenience groups
group "default" {
    targets = ["all"]
}

group "all" {
    targets = ["runtime", "cuda", "cuda-arch", "cpu", "rocm", "xpu", "mcp", "mcp-convert", "comfyctl"]
}

group "core" {
    targets = ["runtime-cuda", "runtime-cpu", "runtime-rocm", "runtime-xpu", "core-cuda", "core-cpu", "core-rocm", "core-xpu"]
}

group "runtime" {
    targets = ["runtime-cuda", "runtime-cpu", "runtime-rocm", "runtime-xpu"]
}

group "cuda" {
    targets = [
        "runtime-cuda",
        "core-cuda",
        "complete-cuda"
    ]
}

// Architecture-specific wheels are version-coupled to PyTorch/CUDA. Build
// them separately so an upstream ABI change cannot block generic CUDA images.
group "cuda-arch" {
    targets = [
        "complete-cuda-sm80",
        "complete-cuda-sm86",
        "complete-cuda-sm89",
        "complete-cuda-sm90",
        "complete-cuda-sm120"
    ]
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
