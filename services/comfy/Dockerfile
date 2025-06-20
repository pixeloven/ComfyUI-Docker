# Build arguments
ARG PYTORCH_VERSION=2.5.1
ARG CUDA_VERSION=12.4
ARG CUDNN_VERSION=9

# Single unified image - onnxruntime-gpu handles both GPU and CPU automatically
FROM pytorch/pytorch:${PYTORCH_VERSION}-cuda${CUDA_VERSION}-cudnn${CUDNN_VERSION}-runtime AS base

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_PREFER_BINARY=1

RUN --mount=type=cache,target=/var/cache/apt \
  apt-get update && \
  apt-get install -y git wget curl jq build-essential ffmpeg libgl1 libglib2.0-0 && \
  apt-get clean && \
  pip install --no-input --upgrade pip

FROM base AS application

RUN useradd -m -s /bin/bash app
USER app
WORKDIR /home/app
SHELL ["/bin/bash", "--login", "-c"]

# Setup ComfyUI project
RUN git clone --branch v0.3.39 --depth 1 https://github.com/comfyanonymous/ComfyUI.git .
COPY --chown=app:app . .

# Setup venv
ENV VIRTUAL_ENV=/home/app/.venv
RUN --mount=type=cache,target=~/.cache/pip \
  mkdir -p ~/.local/bin && \
  python -m venv $VIRTUAL_ENV

ENV PATH="/home/app/.local/bin:$PATH"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install dependencies - onnxruntime-gpu automatically falls back to CPU when CUDA unavailable
RUN --mount=type=cache,target=~/.cache/pip \
  pip install -r requirements.txt && \
  pip install onnxruntime-gpu && \
  chmod u+x ./entrypoint.sh

ENV NVIDIA_VISIBLE_DEVICES=all
ENV CLI_ARGS=""

EXPOSE 8188
ENTRYPOINT ["./entrypoint.sh"]
CMD python -u main.py --listen --port 8188 ${CLI_ARGS}

# Explore how we can use the CLI to do this instead
# https://docs.comfy.org/installation/system_requirements
# https://docs.comfy.org/comfy-cli/getting-started
# https://pythonspeed.com/articles/activate-conda-dockerfile/
# https://pythonspeed.com/articles/multi-stage-docker-python/
# pip install comfy-cli && \
# comfy install