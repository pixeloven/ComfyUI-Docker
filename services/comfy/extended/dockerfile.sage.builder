FROM nvidia/cuda:12.9.1-cudnn-devel-ubuntu24.04 AS sageattention-builder

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_PREFER_BINARY=1

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    python3 \
    python3-dev \
    python3-venv \
    python3-pip \
    python-is-python3 \
    git \
    ninja-build && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install PyTorch and build dependencies (using available version)
RUN pip install torch==2.7.1+cu128 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128 && \
    pip install ninja wheel packaging

# Build SageAttention 2++ from source
WORKDIR /tmp
RUN git clone https://github.com/woct0rdho/SageAttention.git && \
    cd SageAttention && \
    export TORCH_CUDA_ARCH_LIST="8.0 8.6 8.9 9.0 12.0" && \
    export SAGEATTENTION_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST} && \
    export MAX_JOBS=1 && \
    export NVCC_THREADS=4 && \
    python setup.py bdist_wheel && \
    mkdir -p /wheels && \
    cp dist/*.whl /wheels/