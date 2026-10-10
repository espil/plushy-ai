# Plushy AI — GPU Docker image
# Base: CUDA 12.1 devel (needed to build trellis/spconv extensions)
FROM nvidia/cuda:12.1.0-cudnn8-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLUSHY_BACKEND=trellis \
    PLUSHY_WORKERS=1

# --- system deps ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3.10-venv python3-pip \
        git git-lfs wget curl ffmpeg \
        libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
        build-essential ninja-build cmake \
    && rm -rf /var/lib/apt/lists/* \
    && git lfs install

RUN ln -sf /usr/bin/python3.10 /usr/bin/python

WORKDIR /app

# --- torch (CUDA 12.1) first, so downstream wheels match ---
RUN pip install --upgrade pip setuptools wheel \
 && pip install torch==2.3.1 torchvision==0.18.1 --index-url https://download.pytorch.org/whl/cu121

# --- python deps ---
COPY requirements.txt .
RUN pip install -r requirements.txt

# --- TRELLIS (no PyPI release — install from source) ---
# Comment out if you only use the Hunyuan3D backend.
RUN git clone --depth 1 https://github.com/microsoft/TRELLIS.git /opt/TRELLIS \
 && pip install -e /opt/TRELLIS

# --- app code ---
COPY app.py pipeline.py ./
RUN mkdir -p uploads outputs

# Model weights download at runtime (first request warms them up).
# To bake weights into the image instead, uncomment:
# RUN python -c "from pipeline import get_pipeline; get_pipeline().warmup()"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
