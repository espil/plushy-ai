"""
pipeline_sprite.py — Plushy AI 2D sprite pipeline.

Text prompt -> SDXL-Turbo -> background removal -> transparent PNG,
ready to use as a billboard sprite in a game engine.

Much lighter than the 3D pipeline: seconds per sprite on an 8GB GPU,
no mesh extraction, no CUDA extensions beyond torch itself.

Backends:
  - "mock"  (PLUSHY_MOCK=1): procedural placeholder PNG, no model needed.
  - "sdxl"  (default): stabilityai/sdxl-turbo, fp16 on CUDA.

Usage:
    from pipeline_sprite import SpritePipeline, SpriteOptions
    pipe = SpritePipeline()
    img = pipe.generate("a pine tree", SpriteOptions(seed=0))  # PIL RGBA
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("plushy.sprite")

MOCK = os.getenv("PLUSHY_MOCK", "0") == "1"
SPRITE_MODEL = os.getenv("PLUSHY_SPRITE_MODEL", "stabilityai/sdxl-turbo")
DEVICE = "cuda" if not MOCK else "cpu"

# Prompt suffix that keeps outputs sprite-friendly. The background gets
# removed by rembg anyway; asking for plain white makes removal cleaner.
# v2 (2026-10-11): explicit "fully visible / nothing cut off" — SDXL-Turbo
# tended to crop subjects at frame edges, and rembg then clipped the
# cropped parts further, producing "incomplete" sprites.
SPRITE_SUFFIX = (", game asset sprite, single object, fully visible, nothing cut off, "
                 "centered, isolated on a solid pure white background, "
                 "clean silhouette, sharp details")

# Architecture preset (city project): billboard buildings must read as flat
# facades — a 3/4 perspective view looks wrong on a camera-facing plane.
ARCH_SUFFIX = (", architectural elevation, straight-on front view, flat facade, "
               "fully visible, nothing cut off, isolated on a solid pure white background, "
               "clean silhouette, sharp details")

# 3D model style (everplanet-like): polished 3D game-model look for the city —
# cute stylized 3D, three-quarter view showing volume, finished asset quality.
# Replaces the subject suffix entirely (its own framing, not flat).
STYLE_3D = (", polished 3D video game model, cute stylized 3D like everplanet buildings, "
            "three-quarter view showing depth and volume, soft studio lighting, "
            "vibrant colors, clean stylized geometry, finished game asset quality, "
            "isolated on a solid pure white background, fully visible, nothing cut off")

# Chibi style (MapleStory 2-like): big head tiny body, cute 3D game character.
# Replaces the subject suffix (avoids conflicting style descriptors).
STYLE_CHIBI = (", chibi character style, huge round head tiny cute body, "
               "3D game character like maplestory 2, soft 3D render shading, "
               "vibrant game colors, clean bold silhouette, fully visible, "
               "nothing cut off, isolated on solid white background")

# Paper-doll "wear" suffix: img2img prompts that dress the blank body.
# Keeps pose/proportions; only the described item is added.
WEAR_SUFFIX = (", wearing this item, keep the exact same body pose, proportions and "
               "camera angle, only add the described clothing or hair, "
               "seamless game sprite, fully visible, nothing cut off")

# 2.5D game style (pokemon sword/shield-like): stylized, bold readable
# silhouettes, vibrant colors, soft cel-shading. Appended after the subject
# suffix when style="2.5d".
STYLE_2_5D = (", stylized 2.5D video game asset, pokemon sword and shield style graphics, "
              "clean bold readable silhouette, vibrant saturated colors, "
              "soft cel shading, crisp clean edges")


@dataclass
class SpriteOptions:
    prompt: str = ""
    negative_prompt: str = ("blurry, watermark, text, cropped, cut off, out of frame, "
                            "partial object, multiple objects, dark, silhouette, "
                            "black background, gloomy, night, deformed, broken, incomplete")
    width: int = 512
    height: int = 512
    seed: int = 0
    num_inference_steps: int = 6       # SDXL-Turbo is designed for 1-4; 6-8 adds detail
    guidance_scale: float = 0.0        # SDXL-Turbo wants 0.0
    remove_background: bool = True
    sprite_style: bool = True          # append style suffix
    subject_type: str = "object"       # "object" -> SPRITE_SUFFIX, "building" -> ARCH_SUFFIX
    style: str = "default"             # "2.5d" appends STYLE_2_5D; "3d"/"chibi" replace subject suffix
    crisp_alpha: bool = True           # binarize alpha: kills semi-transparent fringes


ProgressCallback = Callable[[float, str], None]


class _MockSpriteBackend:
    """Procedural placeholder sprite — a simple tree-ish blob."""

    def generate(self, opts: SpriteOptions,
                 progress: Optional[ProgressCallback] = None) -> "Image.Image":
        from PIL import Image, ImageDraw
        if progress:
            progress(0.5, "mock sprite")
        w, h = opts.width, opts.height
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        cx, cy = w // 2, h // 2
        # trunk + canopy, seeded for variety
        import random
        rng = random.Random(opts.seed)
        trunk_w = w // 12
        d.rectangle([cx - trunk_w // 2, cy, cx + trunk_w // 2, cy + h // 4],
                    fill=(101, 67, 33, 255))
        for _ in range(5):
            r = w // 5 + rng.randint(-8, 8)
            ox = rng.randint(-w // 8, w // 8)
            oy = rng.randint(-h // 6, 0)
            d.ellipse([cx - r + ox, cy - r + oy, cx + r + ox, cy + r + oy],
                      fill=(63, 125, 68, 255))
        if progress:
            progress(1.0, "mock sprite done")
        return img

    def img2img(self, opts: SpriteOptions, init_image: "Image.Image",
                strength: float = 0.6,
                progress: Optional[ProgressCallback] = None) -> "Image.Image":
        # mock: tint the init image so the pipeline is testable without GPU
        from PIL import Image
        if progress:
            progress(0.5, "mock img2img")
        img = init_image.convert("RGBA").copy()
        tint = Image.new("RGBA", img.size, (255, 120, 120, 60))
        img = Image.alpha_composite(img, tint)
        if progress:
            progress(1.0, "mock img2img done")
        return img


class _SDXLSpriteBackend:
    """stabilityai/sdxl-turbo text-to-image."""

    def __init__(self):
        self._pipe = None
        self._i2i = None

    def _load_i2i(self):
        if self._i2i is not None:
            return
        import torch
        log.info("loading img2img model %s ...", SPRITE_MODEL)
        from diffusers import AutoPipelineForImage2Image
        # stabilityai/sdxl-turbo is a gated model: the Hugging Face account
        # must accept its license, and downloads need HF_TOKEN set.
        import os
        token = os.environ.get("HF_TOKEN") or None
        pipe = AutoPipelineForImage2Image.from_pretrained(
            SPRITE_MODEL,
            torch_dtype=torch.float16 if DEVICE == "cuda" else torch.float32,
            variant="fp16" if DEVICE == "cuda" else None,
            token=token,
        )
        if DEVICE == "cuda":
            pipe.to("cuda")
            try:
                pipe.enable_xformers_memory_efficient_attention()
            except Exception:
                pass
        self._i2i = pipe
        log.info("img2img model loaded")

    def img2img(self, opts: SpriteOptions, init_image: "Image.Image",
                strength: float = 0.6,
                progress: Optional[ProgressCallback] = None) -> "Image.Image":
        """Dress/edit an existing sprite: keeps structure, changes appearance.
        strength 0.5-0.7 = keep pose, add item. Higher = more change."""
        self._load_i2i()
        import torch
        from PIL import Image
        prompt = opts.prompt + WEAR_SUFFIX
        if progress:
            progress(0.2, "wearing item")
        gen = torch.Generator(device=DEVICE).manual_seed(opts.seed)
        # img2img needs RGB on a solid background: composite over white
        base = Image.new("RGB", init_image.size, (255, 255, 255))
        base.paste(init_image.convert("RGBA"), mask=init_image.convert("RGBA").split()[3])
        steps = max(1, min(opts.num_inference_steps, 12))

        def _step_cb2(pipe, i, ts, kwargs):
            if progress:
                progress(0.2 + 0.6 * (i + 1) / steps, f"step {i + 1}/{steps}")
            return kwargs

        out = self._i2i(
            prompt=prompt,
            negative_prompt=opts.negative_prompt,
            image=base,
            strength=max(0.1, min(strength, 1.0)),
            num_inference_steps=steps,
            guidance_scale=opts.guidance_scale,
            generator=gen,
            callback_on_step_end=_step_cb2,
        )
        img = out.images[0].convert("RGBA")
        if progress:
            progress(0.8, "item worn")
        return img

    def load(self):
        if self._pipe is not None:
            return
        import torch
        log.info("loading sprite model %s ...", SPRITE_MODEL)
        from diffusers import AutoPipelineForText2Image
        # stabilityai/sdxl-turbo is a gated model: the Hugging Face account
        # must accept its license, and downloads need HF_TOKEN set.
        token = os.environ.get("HF_TOKEN") or None
        pipe = AutoPipelineForText2Image.from_pretrained(
            SPRITE_MODEL,
            torch_dtype=torch.float16 if DEVICE == "cuda" else torch.float32,
            variant="fp16" if DEVICE == "cuda" else None,
            token=token,
        )
        if DEVICE == "cuda":
            pipe.to("cuda")
            try:
                pipe.enable_xformers_memory_efficient_attention()
            except Exception:
                pass
        self._pipe = pipe
        log.info("sprite model loaded")

    def generate(self, opts: SpriteOptions,
                 progress: Optional[ProgressCallback] = None) -> "Image.Image":
        self.load()
        import torch
        if opts.style == "3d":
            suffix = STYLE_3D  # own framing (3/4 view), replaces subject suffix
        elif opts.style == "chibi":
            suffix = STYLE_CHIBI  # own style, replaces subject suffix
        else:
            suffix = ARCH_SUFFIX if opts.subject_type == "building" else SPRITE_SUFFIX
            if opts.style == "2.5d":
                suffix += STYLE_2_5D
        prompt = opts.prompt + (suffix if opts.sprite_style else "")
        if progress:
            progress(0.2, "generating sprite")
        gen = torch.Generator(device=DEVICE).manual_seed(opts.seed)
        steps = max(1, min(opts.num_inference_steps, 12))

        def _step_cb(pipe, i, ts, kwargs):
            if progress:
                progress(0.2 + 0.6 * (i + 1) / steps, f"step {i + 1}/{steps}")
            return kwargs

        out = self._pipe(
            prompt=prompt,
            negative_prompt=opts.negative_prompt,
            width=opts.width,
            height=opts.height,
            num_inference_steps=steps,
            guidance_scale=opts.guidance_scale,
            generator=gen,
            callback_on_step_end=_step_cb,
        )
        img = out.images[0].convert("RGBA")
        if progress:
            progress(0.8, "sprite generated")
        return img


def _transparent_frac(img: "Image.Image") -> float:
    import numpy as np
    a = np.array(img.convert("RGBA"))[:, :, 3]
    return float((a == 0).mean())


def _dark_bg_fallback(img: "Image.Image", thresh: int = 48) -> "Image.Image | None":
    """Flood-fill fallback for when rembg fails on dark/black backgrounds.

    Removes border-connected near-black regions. Returns None when unsafe
    (subject touches the image edge — flood fill would eat into it).
    Tested 2026-10-11 on 26 real failed sprites: 5 significantly improved,
    0 made worse, 12 skipped as unsafe.
    """
    import numpy as np
    from PIL import Image
    rgb = np.array(img.convert("RGB"))
    dark = rgb.max(axis=2) < thresh
    h, w = dark.shape
    border = np.concatenate([dark[0, :], dark[-1, :], dark[:, 0], dark[:, -1]])
    if border.mean() < 0.95:
        return None
    mask = np.zeros((h, w), dtype=bool)
    mask[0, :] = dark[0, :]
    mask[-1, :] = dark[-1, :]
    mask[:, 0] = dark[:, 0]
    mask[:, -1] = dark[:, -1]
    for _ in range(max(h, w)):
        padded = np.pad(mask, 1)
        grown = (padded[:-2, :-2] | padded[:-2, 1:-1] | padded[:-2, 2:] |
                 padded[1:-1, :-2] | padded[1:-1, 2:] |
                 padded[2:, :-2] | padded[2:, 1:-1] | padded[2:, 2:])
        new = (grown | mask) & dark
        if np.array_equal(new, mask):
            break
        mask = new
    alpha = np.where(mask, 0, 255).astype(np.uint8)
    return Image.fromarray(np.dstack([rgb, alpha]), "RGBA")


def _crisp_alpha(img: "Image.Image", thresh: int = 127) -> "Image.Image":
    """Binarize the alpha channel: kills semi-transparent fringes/halos that
    make sprites look ghostly in-game. Game sprites need fully opaque or fully
    transparent pixels."""
    import numpy as np
    from PIL import Image
    arr = np.array(img.convert("RGBA"))
    arr[:, :, 3] = np.where(arr[:, :, 3] > thresh, 255, 0).astype(np.uint8)
    return Image.fromarray(arr)


def remove_background_rgba(img: "Image.Image", crisp: bool = True) -> "Image.Image":
    """rembg -> transparent background. No-op in mock mode (already transparent).

    If rembg leaves the image mostly opaque (typical when SDXL-Turbo renders a
    black background despite the white-background instruction), tries the
    dark-background flood-fill fallback and keeps whichever is more transparent.

    When crisp=True (default), the alpha channel is binarized at the end so no
    semi-transparent fringe pixels remain — game sprites must be fully opaque
    or fully transparent.
    """
    if MOCK:
        return img
    from rembg import remove
    import numpy as np
    from PIL import Image
    arr = remove(np.array(img.convert("RGB")))
    result = Image.fromarray(arr)
    if _transparent_frac(result) < 0.5:
        fb = _dark_bg_fallback(img)
        if fb is not None and _transparent_frac(fb) > _transparent_frac(result):
            log.info("rembg failed (%.0f%% transparent) — dark-bg fallback used (%.0f%%)",
                     _transparent_frac(result) * 100, _transparent_frac(fb) * 100)
            result = fb
    if crisp:
        result = _crisp_alpha(result)
    return result


class SpritePipeline:
    """Text -> transparent PNG sprite."""

    def __init__(self):
        self._backend = _MockSpriteBackend() if MOCK else _SDXLSpriteBackend()
        log.info("sprite backend: %s (mock=%s)", type(self._backend).__name__, MOCK)

    def generate(self, prompt: str, opts: Optional[SpriteOptions] = None,
                 progress: Optional[ProgressCallback] = None) -> "Image.Image":
        from PIL import Image
        o = opts or SpriteOptions()
        o.prompt = prompt or o.prompt
        img = self._backend.generate(o, progress)
        if o.remove_background and not MOCK:
            if progress:
                progress(0.9, "removing background")
            img = remove_background_rgba(img, crisp=o.crisp_alpha)
        if progress:
            progress(1.0, "done")
        return img

    def img2img(self, prompt: str, init_image: "Image.Image",
                strength: float = 0.6,
                opts: Optional[SpriteOptions] = None,
                progress: Optional[ProgressCallback] = None) -> "Image.Image":
        """Paper-doll 'wear': dress the blank body (or edit a sprite).
        Returns a transparent PNG (background removed unless mock)."""
        o = opts or SpriteOptions()
        o.prompt = prompt or o.prompt
        img = self._backend.img2img(o, init_image, strength, progress)
        if o.remove_background and not MOCK:
            if progress:
                progress(0.9, "removing background")
            img = remove_background_rgba(img, crisp=o.crisp_alpha)
        if progress:
            progress(1.0, "done")
        return img

    def img2img_to_file(self, prompt: str, init_image: "Image.Image", dest: Path,
                        strength: float = 0.6,
                        opts: Optional[SpriteOptions] = None,
                        progress: Optional[ProgressCallback] = None) -> Path:
        img = self.img2img(prompt, init_image, strength, opts, progress)
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, "PNG")
        return dest

    def generate_to_file(self, prompt: str, dest: Path,
                         opts: Optional[SpriteOptions] = None,
                         progress: Optional[ProgressCallback] = None) -> Path:
        img = self.generate(prompt, opts, progress)
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, "PNG")
        return dest
