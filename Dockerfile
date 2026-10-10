# Plushy AI — sprite-only GPU Docker image
# Text -> transparent PNG sprites (SDXL-Turbo + rembg). No 3D pipeline.
FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLUSHY_WORKERS=1

# --- system deps ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3.10-venv python3-pip \
        wget curl ffmpeg \
        libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.10 /usr/bin/python

WORKDIR /app

# --- torch (CUDA 12.1) first, so downstream wheels match ---
RUN pip install --upgrade pip setuptools wheel \
 && pip install torch==2.3.1 torchvision==0.18.1 --index-url https://download.pytorch.org/whl/cu121

# --- python deps ---
COPY requirements.txt .
RUN pip install -r requirements.txt

# --- app code ---
COPY app.py pipeline_sprite.py sprites.py ./
COPY static/ ./static/
RUN mkdir -p outputs

# Model weights (SDXL-Turbo) download at runtime on first generation.
# Cached in /root/.cache/huggingface — mount a volume to keep them:
#   -v plushy-hf:/root/.cache/huggingface

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
