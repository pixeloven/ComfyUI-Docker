# FROM pytorch/pytorch:2.7.0-cuda12.8-cudnn9-runtime AS base
# https://mveg.es/posts/optimizing-pytorch-docker-images-cut-size-by-60percent/

# Explore how we can use the CLI to do this instead
# https://docs.comfy.org/installation/system_requirements
# https://docs.comfy.org/comfy-cli/getting-started
# https://pythonspeed.com/articles/activate-conda-dockerfile/
# https://pythonspeed.com/articles/multi-stage-docker-python/
# pip install comfy-cli && \
# comfy install 

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

ARG PUID=1024
ARG PGID=1024
RUN groupadd -g $PGID comfy && \
    useradd -m -u $PUID -g $PGID comfy

USER comfy

WORKDIR /home/comfy

SHELL ["/bin/bash", "--login", "-c"]
#SHELL ["/bin/bash", "-eux", "-o", "pipefail", "-c"]

ENV VIRTUAL_ENV=/home/comfy/.venv

RUN --mount=type=cache,target=~/.cache/pip \ 
  python -m venv $VIRTUAL_ENV && \
  source $VIRTUAL_ENV/bin/activate

ENV PATH="/home/comfy/.local/bin:$PATH"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN --mount=type=cache,target=~/.cache/pip \
  pip install comfy-cli && \
  comfy --skip-prompt --workspace /home/comfy/app install --nvidia --skip-manager && \
  comfy --skip-prompt set-default /home/comfy/app && \
  comfy --skip-prompt --no-enable-telemetry env

WORKDIR /home/comfy/app

COPY --chown=comfy:comfy . .

RUN chmod +x ./entrypoint.sh ./runner.sh

# # Install popular extensions using Comfy-CLI
# RUN comfy node install ComfyUI-Manager && \
#     comfy node install ComfyUI-to-Python-Extension && \
#     comfy node install ComfyUI-ReActor && \
#     comfy node install ComfyUI-WD14-Tagger

# Set environment variables
ENV CLI_ARGS=""
ENV COMFY_PORT=8188
ENV BASE_DIRECTORY="/data/config/comfy"
ENV OUTPUT_DIRECTORY="/output"

EXPOSE $COMFY_PORT

ENTRYPOINT ["./entrypoint.sh"]

CMD ["bash", "./runner.sh"]

# maybe comfy cli supports install of extensions?