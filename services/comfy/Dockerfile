FROM pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime

ENV DEBIAN_FRONTEND=noninteractive 
ENV PIP_PREFER_BINARY=1
ENV APPLICATION_ROOT=/stable-diffusion
ENV NVIDIA_VISIBLE_DEVICES=all 
ENV PYTHONPATH="${PYTHONPATH}:${PWD}" 
ENV CLI_ARGS=""

WORKDIR ${APPLICATION_ROOT}

# Explore how we can use the CLI to do this instead
# https://docs.comfy.org/installation/system_requirements
# https://docs.comfy.org/comfy-cli/getting-started
RUN apt-get update && \ 
  apt-get install -y git && \
  apt-get clean && \
  git clone --branch v0.3.19 --depth 1 https://github.com/comfyanonymous/ComfyUI.git ${APPLICATION_ROOT}

COPY . .

RUN --mount=type=cache,target=/root/.cache/pip \
  pip install -r requirements.txt && \
  chmod u+x ./entrypoint.sh 

EXPOSE 7860

ENTRYPOINT ["./entrypoint.sh"]
CMD python -u main.py --listen --port 7860 ${CLI_ARGS}
