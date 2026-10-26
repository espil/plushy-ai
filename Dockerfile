# syntax=docker/dockerfile:1
# Plushy AI - sprite + image-to-3D GPU Docker image
# Sprites: text -> transparent PNG (SDXL-Turbo + rembg).
# 3D: image -> textured GLB via Stable Fast 3D (SF3D), isolated in its
# own venv (/opt/sf3d-venv) so its pins never disturb the sprite env.
# The devel base (nvcc included) is required because SF3D's texture_baker
# is a CUDA extension compiled at install time.
FROM nvidia/cuda:12.1.0-cudnn8-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PLUSHY_WORKERS=1

# --- system deps ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3.10-venv python3-pip python3.10-dev \
        wget curl ffmpeg git build-essential ninja-build gltfpack \
        libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.10 /usr/bin/python

WORKDIR /app

# --- torch (CUDA 12.1) first, so downstream wheels match ---
# pip downloads go through a BuildKit cache mount: if the build dies
# mid-download (DNS/network hiccup on a ~730MB wheel), a rerun resumes
# from the cached partials instead of starting over.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --retries 10 --timeout 120 --upgrade pip setuptools wheel \
 && pip install --resume-retries 20 --retries 10 --timeout 120 \
      torch==2.3.1 torchvision==0.18.1 --index-url https://download.pytorch.org/whl/cu121

# --- python deps (sprite pipeline) ---
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --retries 10 --timeout 120 -r requirements.txt

# --- SF3D image-to-3D engine (isolated venv, pinned upstream commit) ---
# USE_CUDA=1 matters: there is no GPU at image-build time, and the
# texture_baker would otherwise silently build its CPU fallback.
# Split into separate RUN steps on purpose: if one sub-step fails, the
# build error names that exact step instead of one long chain.
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/sf3d-venv \
 && /opt/sf3d-venv/bin/pip install --retries 10 --timeout 120 --upgrade pip "setuptools==69.5.1" wheel ninja \
 && /opt/sf3d-venv/bin/pip install --resume-retries 20 --retries 10 --timeout 120 \
      torch==2.4.1 torchvision==0.19.1 --index-url https://download.pytorch.org/whl/cu121
# torch 2.4.1, not 2.3.1: SF3D at the pinned commit imports
# torch.amp.custom_fwd/custom_bwd (sf3d/models/network.py), which
# exist only in torch >= 2.4 - with 2.3.1 the self-test died on that
# ImportError (measured in Han's run-all log, 2026-10-25). 2.4.1 also
# bundles the cuDNN 9 wheel the onnxruntime pin below needs.

RUN git clone https://github.com/Stability-AI/stable-fast-3d.git /opt/stable-fast-3d \
 && cd /opt/stable-fast-3d \
 && git checkout ff21fc491b4dc5314bf6734c7c0dabd86b5f5bb2

# SF3D's requirements compile two local C++/CUDA extensions
# (texture_baker, uv_unwrapper) plus small compiled deps - the most
# failure-prone part of the build, kept as its own step.
# The two local packages have no pyproject.toml and their setup.py
# imports torch, which pip's build isolation hides (build env gets
# only setuptools+wheel) - so: remote deps first with normal builds,
# then the local packages with --no-build-isolation against the
# venv's torch.
# onnxruntime-gpu comes from Microsoft's CUDA-12 feed as an exact
# wheel URL (binary-verified 2026-10-25, after Han's run-all log
# measured "rembg session providers: ['CPUExecutionProvider']"):
# PyPI's 1.18.1 is a CUDA 11 build - its provider needs
# libcublas(Lt).so.11, absent in this CUDA 12.1 image, so it cannot
# load at all; PyPI's CUDA 12 builds (1.19+) carry the sysfs
# device-discovery that fails noisily in containers. The feed's
# 1.18.1 is a CUDA 12 + cuDNN 9 build whose binaries contain no
# device-discovery code at all (zero matching strings, checked
# directly), and its provider NEEDs only libraries that exist
# here: libcublas.so.12 in /usr/local/cuda/lib64, libcudnn.so.9 in
# torch 2.4.1's bundled wheel - both on LD_LIBRARY_PATH via
# pipeline_3d._sf3d_env. A direct URL (not a version pin) so pip
# can never substitute PyPI's same-version CUDA 11 wheel.
RUN --mount=type=cache,target=/root/.cache/pip \
    cd /opt/stable-fast-3d \
 && grep -v '^\./' requirements.txt > /tmp/sf3d-remote-requirements.txt \
 && /opt/sf3d-venv/bin/pip install --retries 10 --timeout 120 -r /tmp/sf3d-remote-requirements.txt \
 && /opt/sf3d-venv/bin/pip install --retries 10 --timeout 120 "https://aiinfra.pkgs.visualstudio.com/2692857e-05ef-43b4-ba9c-ccf1c22c437c/_packaging/9387c3aa-d9ad-4513-968c-383f6f7f53b8/pypi/download/onnxruntime-gpu/1.18.1/onnxruntime_gpu-1.18.1-cp310-cp310-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl#sha256=4e9a52f5d43a84fe29e135da6bf10daa18836c81bed9060a5924efd6afc0d259" \
 && USE_CUDA=1 TORCH_CUDA_ARCH_LIST="8.6;8.9" /opt/sf3d-venv/bin/pip install --no-build-isolation --retries 10 --timeout 120 ./texture_baker ./uv_unwrapper

# --- app code ---
# (The run commands mount the repo over /app, so git pull alone updates code.
#  These COPYs are fallback for running without the mount.)
COPY *.py ./
COPY prompts/ ./prompts/
COPY static/ ./static/
COPY tools/ ./tools/
RUN mkdir -p outputs city_sprites paperdoll

# Model weights (SDXL-Turbo, SF3D) download at runtime on first use.
# Cached in /root/.cache/huggingface - mount a volume to keep them:
#   -v plushy-hf:/root/.cache/huggingface

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
