# comfyctl — the CLI as an image: `comfyctl fetch` resolves, verifies and
# materialises ComfyUI model locks. It replaced the `fetch` image in 6.0.0
# (#197), when comfyfetch was absorbed into comfyctl.
#
# Python rather than shell. The shell version accumulated seven distinct classes
# of silent bug -- the worst being a yq whose escape handling differs between
# PATCH releases, which once made the record parser match nothing, process zero
# files and exit 0.
#
# The build context is services/, the uv workspace root, so the image installs
# exactly what services/uv.lock pins, hash-checked (#177), as the mcp image
# does. Only comfyctl and its dependencies: comfyrelay ships as the mcp image,
# so here `comfyctl relay` says it isn't in this build.
# dockerfile.comfy.ctl.dockerignore, beside this file, is the context filter.
#
# Consumers pin by digest.

ARG PYTHON_VERSION=3.13

# The uv that installs from the lock, the one the mcp image uses. Build stage only.
FROM ghcr.io/astral-sh/uv:0.11.23@sha256:d0a0a753ab981624b49c97abc98821c1c09f4ca69d1ef5cee69c501be3d88479 AS uv

FROM python:${PYTHON_VERSION}-alpine AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1
WORKDIR /src
# The lock and every member's pyproject first (uv reads the whole workspace),
# so the dependency layer only rebuilds when they change. --frozen installs the
# lock as written and fails rather than re-resolving; every wheel is checked
# against its lock hash. No bytecode is compiled: not caching it is irrelevant
# next to downloading gigabytes.
COPY pyproject.toml uv.lock ./
COPY comfyctl/pyproject.toml comfyctl/README.md comfyctl/
COPY comfyrelay/pyproject.toml comfyrelay/README.md comfyrelay/
RUN uv sync --frozen --no-dev --package comfyctl --no-install-workspace
# Then comfyctl itself, not editable, so /src can go.
COPY comfyctl/comfyctl comfyctl/comfyctl
RUN uv sync --frozen --no-dev --package comfyctl --no-editable

FROM python:${PYTHON_VERSION}-alpine

# pip, setuptools and the build machinery are removed: nothing at runtime
# installs anything, and leaving them is both weight and attack surface. The
# venv was built against this same interpreter, which it links to.
#
# Each `|| true` is INSIDE braces. `&&` and `||` bind equally and left to right,
# so a bare `… && x || true && …` also swallows the failure before it.
RUN { pip uninstall -y pip setuptools wheel 2>/dev/null || true; } \
 && rm -rf /usr/local/lib/python*/ensurepip \
           /usr/local/lib/python*/idlelib \
           /usr/local/lib/python*/lib2to3 \
           /usr/local/lib/python*/tkinter \
           /usr/local/lib/python*/turtledemo \
           /usr/local/lib/python*/test \
 && { find /usr/local -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true; }

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1

# Prove the binary and every verb resolve at BUILD time. A missing console
# script is a green build that fails on the next scale-up.
RUN comfyctl --version > /dev/null \
 && comfyctl fetch --help > /dev/null \
 && for verb in build resolve fetch check facts; do \
      comfyctl fetch "$verb" --help > /dev/null || exit 1; \
    done

# The keys the other images use. Not org.opencontainers.image.version: on the
# ComfyUI and mcp images it states the ComfyUI inside, and there is none here.
LABEL org.opencontainers.image.source="https://github.com/pixeloven/ComfyUI-Docker" \
      org.opencontainers.image.description="comfyctl: resolve, verify and materialise ComfyUI model locks" \
      org.opencontainers.image.licenses="MIT"

# Writes to a mounted model volume, so it must run as a non-root uid whose
# ownership the consuming pod or compose file can arrange. NFS writes in
# Harmony's cluster need fsGroup 3000; the uid itself is the consumer's to
# choose.
USER 1000
# The command itself, so arguments name the group and the verb:
# `<image> fetch fetch /lock.yaml /app --apply`, `<image> fetch check …`.
# The fetch image's entrypoint was `comfyctl fetch fetch`.
ENTRYPOINT ["comfyctl"]
