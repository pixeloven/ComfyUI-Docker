FROM pytorch/pytorch:2.7.0-cuda12.8-cudnn9-runtime AS base

ENV DEBIAN_FRONTEND=noninteractive 
ENV PIP_PREFER_BINARY=1

RUN --mount=type=cache,target=/var/cache/apt \ 
  apt-get update && \ 
  apt-get install -y --no-install-recommends git wget curl jq ffmpeg libgl1-mesa-glx libglib2.0-0 && \
  apt-get clean && \
  pip install --no-input --upgrade pip

FROM base AS application

RUN useradd -m -s /bin/bash comfy

USER comfy

WORKDIR /home/comfy/app

SHELL ["/bin/bash", "--login", "-c"]

# Setup ComfyUI project
RUN git clone --branch v0.3.39 --depth 1 https://github.com/comfyanonymous/ComfyUI.git .

COPY --chown=comfy:comfy . .

# Setup venv
# https://pythonspeed.com/articles/activate-virtualenv-dockerfile/
ENV VIRTUAL_ENV=/home/comfy/app/.venv
RUN --mount=type=cache,target=~/.cache/pip \ 
  mkdir -p ~/.local/bin && \
  python -m venv $VIRTUAL_ENV

ENV PATH="/home/comfy/.local/bin:$PATH"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
# ENV PYTHONPATH="${PYTHONPATH}:${PWD}"

# Activate environment and install dependencies
# Should make ONNX optional by moving this into a configuration file that can be alterated at run time
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