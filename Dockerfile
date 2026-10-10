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

# --- TRELLIS (no PyPI release — source checkout, made importable via PYTHONPATH) ---
# Comment out if you only use the Hunyuan3D backend.
# Installs the FULL official --basic dependency set from TRELLIS's setup.sh
# (no more hand-guessing deps one failure at a time). Attention runs on
# xformers (ATTN_BACKEND) so no flash-attn source build is needed. Versions are
# pinned to the numpy-1.x / torch-2.3 era: newer releases demand numpy>=2
# which breaks torch 2.3.
ENV ATTN_BACKEND=xformers \
    PYTHONPATH=/opt/TRELLIS
RUN git clone --depth 1 --recursive https://github.com/microsoft/TRELLIS.git /opt/TRELLIS \
 && pip install spconv-cu121 "timm==0.9.16" "transformers==4.46.3" \
      "huggingface_hub==0.26.5" "open3d==0.18.0" "plyfile==1.1.2" \
      easydict "opencv-python-headless==4.10.0.84" ninja imageio imageio-ffmpeg \
      xatlas pyvista pymeshfix igraph \
      "git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8" \
 && pip install kaolin -f https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.3.1_cu121.html \
 && python -c "from trellis.pipelines import TrellisImageTo3DPipeline; \
               import trellis.models.structured_latent_vae.decoder_mesh; \
               from trellis.representations.mesh import flexicubes; \
               print('TRELLIS import chain OK')"

# --- app code ---
COPY app.py pipeline_3d.py pipeline_sprite.py batch.py sprites.py lowvram_patch.py citygen.py ./
COPY static/ ./static/
RUN mkdir -p uploads outputs

# Model weights download at runtime (first request warms them up).
# To bake weights into the image instead, uncomment:
# RUN python -c "from pipeline import get_pipeline; get_pipeline().warmup()"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
