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

# --- Hunyuan3D QUALITY engine (isolated venv, added 2026-11-26) ---
# The quality backend behind PLUSHY_3D_BACKEND=hunyuan: Hunyuan3D-
# 2mini shape + Hunyuan3D-2.0 paint (hy3dgen), driven by
# tools/hunyuan_driver.py. Same isolation discipline as SF3D: its own
# venv (/opt/hunyuan-venv), its own code tree (/opt/Hunyuan3D-2), so
# its pins can never disturb the sprite or SF3D environments.
# The code pin is a DATE pin (last commit before 2025-10-20, the era
# of the pinned model snapshots - the HF model repos were last
# modified 2025-10-17): the exact upstream HEAD hash could not be
# re-verified from the author's environment, and a floating clone
# would not be reproducible.
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/hunyuan-venv \
 && /opt/hunyuan-venv/bin/pip install --retries 10 --timeout 120 --upgrade pip "setuptools==69.5.1" wheel ninja \
 && /opt/hunyuan-venv/bin/pip install --resume-retries 20 --retries 10 --timeout 120 \
      torch==2.4.1 torchvision==0.19.1 --index-url https://download.pytorch.org/whl/cu121

RUN git clone https://github.com/Tencent-Hunyuan/Hunyuan3D-2.git /opt/Hunyuan3D-2 \
 && cd /opt/Hunyuan3D-2 \
 && git checkout $(git rev-list -1 --before="2025-10-20T00:00:00Z" HEAD)

# requirements.txt also lists the demo stack (gradio/fastapi) - it
# lands only in this isolated venv, so it is installed as shipped.
# Its onnxruntime is the CPU build: hy3dgen uses rembg only as a
# light preprocessing step, unlike SF3D's GPU rembg path.
# The texgen custom_rasterizer is a compiled CUDA extension, built
# as its own step (same failure-naming discipline as SF3D's).
#
# ERA PINS (added 2026-11-26 after Han's first quality run failed):
# upstream requirements.txt pins NOTHING, so a 2026 build resolved
# diffusers 0.41.0 + transformers 5.20.2 against the torch==2.4.1
# pinned above - diffusers 0.41 calls torch.accelerator (torch
# >= 2.6) and every conversion died at import with
# "AttributeError: module 'torch' has no attribute 'accelerator'".
# The four pins below are the stack Hunyuan3D-2 shipped against;
# they are resolved in the SAME pip run as requirements.txt so the
# resolver picks a compatible demo stack around them instead of a
# post-install downgrade fighting it.
RUN --mount=type=cache,target=/root/.cache/pip \
    cd /opt/Hunyuan3D-2 \
 && /opt/hunyuan-venv/bin/pip install --retries 10 --timeout 120 -r requirements.txt \
      "diffusers==0.31.0" "transformers==4.46.3" \
      "huggingface-hub==0.26.2" "tokenizers==0.20.3"

# Engine revision stamp: run_quality_sample.py rebuilds the image
# whenever the stamp inside it differs from the runner's ENGINE_REV,
# so a Dockerfile engine fix can never be silently skipped by an
# already-built image. Bump both together.
RUN echo "2" > /opt/hunyuan-venv/PLUSHY_ENGINE_REV

RUN cd /opt/Hunyuan3D-2/hy3dgen/texgen/custom_rasterizer \
 && TORCH_CUDA_ARCH_LIST="8.6;8.9" /opt/hunyuan-venv/bin/python setup.py install

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
