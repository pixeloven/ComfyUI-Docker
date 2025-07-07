# FROM pytorch/pytorch:2.7.0-cuda12.8-cudnn9-runtime AS base
# https://mveg.es/posts/optimizing-pytorch-docker-images-cut-size-by-60percent/

FROM nvidia/cuda:12.9.1-cudnn-runtime-ubuntu24.04 AS runtime

ENV NVIDIA_VISIBLE_DEVICES=all
ENV DEBIAN_FRONTEND=noninteractive 
ENV PIP_PREFER_BINARY=1

RUN apt-get update && \
  apt-get install -y --no-install-recommends \ 
  build-essential \
  python3 \
  python3-dev \
  python3-pip \
  python3-venv \
  python-is-python3 \
  git \
  wget \
  curl \
  jq \
  ffmpeg \
  libgl1 \
  libglib2.0-0 && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/*

FROM runtime AS application

# ARG PUID=1001
# ARG PGID=1001
# RUN groupadd -g $PGID comfy && \
#     useradd -m -u $PUID -g $PGID comfy

USER ubuntu

WORKDIR /home/ubuntu

SHELL ["/bin/bash", "--login", "-c"]
#SHELL ["/bin/bash", "-eux", "-o", "pipefail", "-c"]

ENV VIRTUAL_ENV=/home/ubuntu/.venv

RUN --mount=type=cache,target=~/.cache/pip \ 
  python -m venv $VIRTUAL_ENV && \
  source $VIRTUAL_ENV/bin/activate

ENV PATH="/home/ubuntu/.local/bin:$PATH"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# @todo this approach is creating a much larger image compared to manual install of the repo 12.7GB -> 15.3GB
# @todo image fails to run python: can't open file '/home/comfy/app/main.py': [Errno 13] Permission denied
# Either the comfy cli or cm-cli can be used for managing the ComfyUI installation and extensions
# @todo https://github.com/Comfy-Org/ComfyUI-Manager/blob/main/docs/en/cm-cli.md

RUN --mount=type=cache,target=~/.cache/pip \
  pip install comfy-cli && \
  comfy --skip-prompt --workspace /home/ubuntu/app install --nvidia --skip-manager && \
  comfy --skip-prompt set-default /home/ubuntu/app && \
  comfy --skip-prompt --no-enable-telemetry env

# # Install popular extensions using Comfy-CLI
# RUN comfy node install ComfyUI-Manager && \
#     comfy node install ComfyUI-to-Python-Extension && \
#     comfy node install ComfyUI-ReActor && \
#     comfy node install ComfyUI-WD14-Tagger

WORKDIR /home/ubuntu/app

# RUN git clone --branch v0.3.43 --depth 1 https://github.com/comfyanonymous/ComfyUI.git .

COPY --chown=ubuntu:ubuntu . .

RUN --mount=type=cache,target=~/.cache/pip \ 
  # pip install -r requirements.txt && \
  pip install -r plugin-requirements.txt && \
  chmod u+x ./entrypoint.sh  && \
  chmod u+x ./runner.sh

# Set environment variables
ENV CLI_ARGS=""
ENV COMFY_PORT=8188
ENV BASE_DIRECTORY="/data/config/comfy"
ENV OUTPUT_DIRECTORY="/output"

EXPOSE $COMFY_PORT

ENTRYPOINT ["./entrypoint.sh"]

CMD ["bash", "./runner.sh"]