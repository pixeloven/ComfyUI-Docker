FROM pytorch/pytorch:2.7.0-cuda12.8-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive 
ENV PIP_PREFER_BINARY=1
ENV NVIDIA_VISIBLE_DEVICES=all 
ENV PYTHONPATH="${PYTHONPATH}:${PWD}" 
ENV CLI_ARGS=""

WORKDIR /app

# Explore how we can use the CLI to do this instead
# https://docs.comfy.org/installation/system_requirements
# https://docs.comfy.org/comfy-cli/getting-started
RUN apt-get update && \ 
  apt-get install -y git && \
  apt-get clean && \
  git clone --branch v0.3.30 --depth 1 https://github.com/comfyanonymous/ComfyUI.git .

COPY . .

RUN --mount=type=cache,target=/root/.cache/pip \
  pip install -r requirements.txt && \
  chmod u+x ./entrypoint.sh 

EXPOSE 7860

ENTRYPOINT ["./entrypoint.sh"]
CMD python -u main.py --listen --port 7860 ${CLI_ARGS}
