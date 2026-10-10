"""
Plushy AI — low-VRAM (8GB) fallback patch for RTX 4060-class GPUs.

WIRED IN — app.py and batch.py both call apply_lowvram() at startup.
No-op unless PLUSHY_LOWVRAM=1 is set.

What the mode does (TRELLIS backend only):
  - inference runs inside torch.autocast(fp16) — the standard 8GB fix,
    roughly halving activation memory with negligible quality loss
  - inference steps clamped 25 -> 12 (fewer diffusion steps = less VRAM,
    still fine for simple plushy-style objects)
  - octree resolution clamped 256 -> 128 (coarser latent grid; mesh gets
    decimated anyway before GLB export)
  - preprocess image size 512 -> 384
  - torch.cuda.empty_cache() after each generation

Quality tradeoff: slightly softer detail than full-res. Good enough for a
first-run smoke test on 8GB; switch the env var off for final-quality runs.

Usage:
  docker run --gpus all -e PLUSHY_LOWVRAM=1 ... plushy-ai python batch.py ...
  (or export PLUSHY_LOWVRAM=1 on the host before `uvicorn app:app` in local mode).
"""

from __future__ import annotations

import functools
import gc
import logging
import os

import pipeline as _p

log = logging.getLogger("plushy.lowvram")


def apply_lowvram() -> bool:
    """Apply the low-VRAM overrides. Returns True if the mode is active."""
    if os.getenv("PLUSHY_LOWVRAM", "0") != "1":
        return False

    log.warning(
        "PLUSHY_LOWVRAM=1 — 8GB mode active: "
        "fp16 autocast, steps<=12, octree<=128, preprocess 384px"
    )

    # --- TRELLIS generate(): clamp cost knobs + fp16 autocast -------------
    _gen = _p._TrellisBackend.generate

    @functools.wraps(_gen)
    def generate(self, image, opts, progress=None):
        import torch

        opts.num_inference_steps = min(opts.num_inference_steps, 12)
        opts.octree_resolution = min(opts.octree_resolution, 128)
        log.info(
            "low-VRAM TRELLIS run: steps=%d octree=%d",
            opts.num_inference_steps, opts.octree_resolution,
        )
        with torch.inference_mode(), torch.autocast(
            device_type="cuda", dtype=torch.float16
        ):
            mesh = _gen(self, image, opts, progress)
        gc.collect()
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass
        return mesh

    _p._TrellisBackend.generate = generate

    # --- preprocess: smaller input image -----------------------------------
    _pre = _p.load_and_preprocess_image

    @functools.wraps(_pre)
    def preprocess(image_path, remove_bg=True, size=512):
        return _pre(image_path, remove_bg, min(size, 384))

    _p.load_and_preprocess_image = preprocess

    return True
