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

# Create a user and group with specified IDs
# ARG PUID=1000
# ARG PGID=1000
# RUN getent passwd && groupadd -g $PGID comfy && \
#   useradd -m -u $PUID -g $PGID comfy

USER ubuntu

WORKDIR /home/ubuntu/app

SHELL ["/bin/bash", "--login", "-c"]

# Setup ComfyUI project
RUN git clone --branch v0.3.39 --depth 1 https://github.com/comfyanonymous/ComfyUI.git .

COPY --chown=ubuntu:ubuntu . .

# Setup venv
# https://pythonspeed.com/articles/activate-virtualenv-dockerfile/
ENV VIRTUAL_ENV=/home/ubuntu/app/.venv
RUN --mount=type=cache,target=~/.cache/pip \ 
  ls -al  && \
  mkdir -p ~/.local/bin && \
  python -m venv $VIRTUAL_ENV

ENV PATH="/home/ubuntu/.local/bin:$PATH"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Activate environment and install dependencies
RUN --mount=type=cache,target=~/.cache/pip \ 
  pip install --no-cache-dir -r requirements.txt && \
  pip install --no-cache-dir -r plugin-requirements.txt && \
  chmod u+x ./entrypoint.sh  && \
  chmod u+x ./runner.sh

ENV CLI_ARGS=""
ENV COMFY_PORT=8188

EXPOSE $COMFY_PORT

ENTRYPOINT ["./entrypoint.sh"]

CMD ["bash", "./runner.sh"]
