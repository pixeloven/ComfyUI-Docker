FROM pytorch/pytorch:2.7.0-cuda12.8-cudnn9-runtime AS base

ENV DEBIAN_FRONTEND=noninteractive 
ENV PIP_PREFER_BINARY=1

RUN --mount=type=cache,target=/var/cache/apt \ 
  apt-get update && \ 
  apt-get install -y git wget curl jq ffmpeg libgl1-mesa-glx libglib2.0-0 && \
  apt-get clean

# Explore how we can use the CLI to do this instead
# https://docs.comfy.org/installation/system_requirements
# https://docs.comfy.org/comfy-cli/getting-started
FROM base AS application

RUN useradd -m -s /bin/bash comfy

USER comfy

WORKDIR /home/comfy/app

# Using CLI (with conda venv -can do venv without all this too)
# python -m pip install -U pip && \
# pip install comfy-cli && \
# conda init bash && \
# conda create -n comfy-env python=3.11 && \
# conda activate comfy-env && \
# comfy install 
RUN --mount=type=cache,target=/comfy/.cache/pip \ 
  git clone --branch v0.3.39 --depth 1 https://github.com/comfyanonymous/ComfyUI.git . && \
  mkdir -p .local/bin && \
  pip install -r requirements.txt && \
  pip install onnxruntime-gpu
# Should make ONNX optional by moving this into a configuration file that can be alterated at run time

COPY --chown=comfy:comfy . .

RUN chmod u+x ./entrypoint.sh 

ENV PATH="/home/comfy/.local/bin:${PATH}"
ENV PYTHONPATH="${PYTHONPATH}:${PWD}"

ENV NVIDIA_VISIBLE_DEVICES=all 
ENV CLI_ARGS=""

EXPOSE 8188

ENTRYPOINT ["./entrypoint.sh"]
CMD python -u main.py --listen --port 8188 ${CLI_ARGS}
