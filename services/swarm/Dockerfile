FROM pytorch/pytorch:2.7.0-cuda12.8-cudnn9-runtime AS base

ENV DEBIAN_FRONTEND=noninteractive 
ENV PIP_PREFER_BINARY=1

#  Was using libgl1-mesa-glx but I think it is deprecated. Also need to upgrade pip.
RUN --mount=type=cache,target=/var/cache/apt \ 
  apt-get update && \ 
  apt-get install -y git wget curl jq build-essential ffmpeg libgl1 libglib2.0-0 && \
  apt-get clean && \
  pip install --no-input --upgrade pip

FROM base AS application

RUN useradd -m -s /bin/bash swarm

USER swarm

WORKDIR /home/swarm/app

SHELL ["/bin/bash", "--login", "-c"]

# Setup SwarmUI project
RUN git clone --branch 0.9.6-Beta --depth 1 https://github.com/mcmonkeyprojects/SwarmUI.git .

COPY --chown=swarm:swarm . .

# Setup venv
# https://pythonspeed.com/articles/activate-virtualenv-dockerfile/
ENV VIRTUAL_ENV=/home/swarm/app/.venv
RUN --mount=type=cache,target=~/.cache/pip \ 
  mkdir -p ~/.local/bin && \
  python -m venv $VIRTUAL_ENV

ENV PATH="/home/swarm/.local/bin:$PATH"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
# ENV PYTHONPATH="${PYTHONPATH}:${PWD}"

# Activate environment and install dependencies
# Should make ONNX optional by moving this into a configuration file that can be alterated at run time
RUN --mount=type=cache,target=~/.cache/pip \ 
  pip install -r requirements.txt && \
  # pip install onnxruntime-gpu && \
  chmod u+x ./entrypoint.sh 

# https://github.com/mcmonkeyprojects/SwarmUI/blob/master/launchtools/StandardDockerfile.docker
# https://github.com/mcmonkeyprojects/SwarmUI/blob/master/launch-linux.sh
# vs
# https://github.com/mcmonkeyprojects/SwarmUI/blob/master/launchtools/launch-standard-docker.sh
# https://github.com/mcmonkeyprojects/SwarmUI/blob/master/launchtools/StandardDockerfile.docker


ENV NVIDIA_VISIBLE_DEVICES=all 
ENV CLI_ARGS=""

EXPOSE 8188

ENTRYPOINT ["./entrypoint.sh"]
CMD python -u main.py --listen --port 8188 ${CLI_ARGS}
