"""
Plushy AI — 3D generation pipeline (image → GLB).

Backends:
  - "trellis"    (default): microsoft/TRELLIS image-to-3D
  - "hunyuan3d"  : tencent/Hunyuan3D-2 shape + texture

Select with env var PLUSHY_BACKEND. Set PLUSHY_MOCK=1 to run without
GPU/weights (generates a placeholder mesh — useful for API testing).

The heavy model imports are lazy so `app.py` can boot fast and the
worker only pays the load cost once.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Optional

import numpy as np
from PIL import Image

log = logging.getLogger("plushy.pipeline")

BACKEND = os.getenv("PLUSHY_BACKEND", "trellis").lower()  # trellis | hunyuan3d
MOCK = os.getenv("PLUSHY_MOCK", "0") == "1"
DEVICE = os.getenv("PLUSHY_DEVICE", "cuda")
TRELLIS_MODEL = os.getenv("PLUSHY_TRELLIS_MODEL", "JeffreyXiang/TRELLIS-image-large")
HUNYUAN_MODEL = os.getenv("PLUSHY_HUNYUAN_MODEL", "tencent/Hunyuan3D-2")

# Single shared thread pool for blocking model inference so the
# asyncio event loop never stalls.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="plushy-infer")

ProgressCallback = Callable[[float, str], None]


@dataclass
class GenerationOptions:
    seed: int = 0
    num_inference_steps: int = 25
    guidance_scale: float = 7.5
    octree_resolution: int = 256
    simplify_ratio: float = 0.9  # mesh decimation target (0-1)
    with_texture: bool = True
    remove_background: bool = True


# Quality presets: accuracy/detail knobs in one flag.
# Geometry detail scales with steps + octree; low-poly look is preserved
# because the mesh is always decimated to simplify_ratio afterwards —
# at low face counts most perceived detail comes from the texture.
QUALITY_PRESETS: dict[str, dict] = {
    "draft":    {"num_inference_steps": 12, "octree_resolution": 128,
                 "simplify_ratio": 0.70},
    "balanced": {"num_inference_steps": 25, "octree_resolution": 256,
                 "simplify_ratio": 0.90},
    "detailed": {"num_inference_steps": 50, "octree_resolution": 512,
                 "simplify_ratio": 0.95},
}


def apply_quality_preset(opts: GenerationOptions, quality: str) -> GenerationOptions:
    """Override an options object with a named quality preset."""
    q = quality.lower()
    if q not in QUALITY_PRESETS:
        raise ValueError(f"unknown quality '{quality}' "
                         f"(choose from {sorted(QUALITY_PRESETS)})")
    for k, v in QUALITY_PRESETS[q].items():
        setattr(opts, k, v)
    return opts


@dataclass
class GenerationResult:
    glb_path: Path
    elapsed_sec: float
    vertex_count: int = 0
    face_count: int = 0
    seed_used: int = 0


# ---------------------------------------------------------------------------
# Image preprocessing
# ---------------------------------------------------------------------------

def load_and_preprocess_image(image_path: Path, remove_bg: bool = True,
                              size: int = 512) -> Image.Image:
    """Load image, optionally remove background, square-pad and resize."""
    img = Image.open(image_path).convert("RGBA")

    if remove_bg:
        try:
            from rembg import remove
            img = remove(img)
            log.info("background removed via rembg")
        except Exception as e:
            log.warning("rembg failed (%s) — continuing without bg removal", e)

    # Composite onto white (TRELLIS/Hunyuan expect opaque RGB)
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bg.paste(img, mask=img.split()[3] if img.mode == "RGBA" else None)
    img = bg

    # Square pad then resize
    w, h = img.size
    side = max(w, h)
    square = Image.new("RGB", (side, side), (255, 255, 255))
    square.paste(img, ((side - w) // 2, (side - h) // 2))
    if side != size:
        square = square.resize((size, size), Image.LANCZOS)
    return square


# ---------------------------------------------------------------------------
# Mesh post-processing / GLB export
# ---------------------------------------------------------------------------

def clean_and_export_glb(mesh, out_path: Path, simplify_ratio: float = 0.9,
                         with_texture: bool = True) -> tuple[int, int]:
    """Clean a trimesh.Trimesh and export a standard .GLB file.

    Returns (vertex_count, face_count).
    """
    import trimesh

    if not isinstance(mesh, trimesh.Trimesh):
        # Some backends return a Scene — merge into one mesh
        if isinstance(mesh, trimesh.Scene):
            combined = trimesh.util.concatenate([
                g for g in mesh.geometry.values()
                if isinstance(g, trimesh.Trimesh)
            ])
            mesh = combined
        else:
            raise TypeError(f"unsupported mesh type: {type(mesh)}")

    # --- cleanup ---
    mesh.merge_vertices()  # weld duplicate verts
    mesh.update_faces(mesh.nondegenerate_faces())  # drop degenerate faces
    mesh.remove_infinite_values()
    trimesh.repair.fix_normals(mesh)
    # Drop tiny disconnected components (floaters)
    try:
        components = mesh.split(only_watertight=False)
        if len(components) > 1:
            components.sort(key=lambda m: m.area, reverse=True)
            # keep components totalling 95% of area
            total = sum(c.area for c in components)
            kept, acc = [], 0.0
            for c in components:
                kept.append(c)
                acc += c.area
                if acc / total >= 0.95:
                    break
            mesh = trimesh.util.concatenate(kept)
            log.info("kept %d/%d components", len(kept), len(components))
    except Exception as e:
        log.warning("component filtering skipped: %s", e)

    # --- decimate (keeps files small, preserves silhouette) ---
    if 0 < simplify_ratio < 1.0:
        try:
            target = max(1000, int(len(mesh.faces) * simplify_ratio))
            mesh = mesh.simplify_quadric_decimation(target)
            log.info("decimated to %d faces", len(mesh.faces))
        except Exception as e:
            log.warning("decimation skipped: %s", e)

    # --- normalize: center on origin, fit in [-1, 1] ---
    mesh.apply_translation(-mesh.centroid)
    scale = 1.0 / max(mesh.extents.max(), 1e-6)
    mesh.apply_scale(scale)
    # Y-up is already standard for both backends; ensure it
    trimesh.repair.fix_normals(mesh)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # trimesh exports GLB with PBR material when vertex colors / uv + texture exist
    mesh.export(out_path, file_type="glb")
    log.info("exported GLB → %s (%d verts, %d faces)", out_path,
             len(mesh.vertices), len(mesh.faces))
    return len(mesh.vertices), len(mesh.faces)


def _mock_mesh() -> "object":
    """Placeholder mesh for PLUSHY_MOCK=1 (no GPU/weights needed)."""
    import trimesh
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=1.0)
    # vertex colors: soft plushy pink gradient
    colors = np.zeros((len(mesh.vertices), 4), dtype=np.uint8)
    ynorm = (mesh.vertices[:, 1] - mesh.vertices[:, 1].min())
    ynorm /= ynorm.max() + 1e-6
    colors[:, 0] = (255 - 40 * ynorm).astype(np.uint8)
    colors[:, 1] = (170 + 30 * ynorm).astype(np.uint8)
    colors[:, 2] = 200
    colors[:, 3] = 255
    mesh.visual.vertex_colors = colors
    return mesh


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------

class _TrellisBackend:
    """Microsoft TRELLIS image-to-3D."""

    def __init__(self):
        self._pipe = None

    def load(self):
        if self._pipe is not None:
            return
        log.info("loading TRELLIS model %s on %s …", TRELLIS_MODEL, DEVICE)
        from trellis.pipelines import TrellisImageTo3DPipeline
        pipe = TrellisImageTo3DPipeline.from_pretrained(TRELLIS_MODEL)
        if DEVICE.startswith("cuda"):
            pipe.cuda()
        self._pipe = pipe
        log.info("TRELLIS loaded")

    def generate(self, image: Image.Image, opts: GenerationOptions,
                 progress: Optional[ProgressCallback] = None):
        self.load()
        import torch
        from trellis.utils import postprocessing_utils

        if progress:
            progress(0.15, "running TRELLIS diffusion")
        with torch.no_grad():
            outputs = self._pipe.run(
                image,
                seed=opts.seed,
                formats=["mesh"],
                preprocess_image=False,
                num_inference_steps=opts.num_inference_steps,
            )
        if progress:
            progress(0.75, "extracting mesh")
        mesh = outputs["mesh"][0]  # trimesh.Trimesh
        return mesh


class _HunyuanBackend:
    """Tencent Hunyuan3D-2 image-to-3D (shape + optional texture)."""

    def __init__(self):
        self._shape_pipe = None
        self._tex_pipe = None

    def load(self):
        if self._shape_pipe is not None:
            return
        log.info("loading Hunyuan3D-2 on %s …", DEVICE)
        from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
        self._shape_pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            HUNYUAN_MODEL)
        if opts_texture := os.getenv("PLUSHY_TEXTURE", "1") == "1":
            try:
                from hy3dgen.texgen import Hunyuan3DPaintPipeline
                self._tex_pipe = Hunyuan3DPaintPipeline.from_pretrained(
                    HUNYUAN_MODEL)
            except Exception as e:
                log.warning("texture pipeline unavailable: %s", e)
        log.info("Hunyuan3D-2 loaded")

    def generate(self, image: Image.Image, opts: GenerationOptions,
                 progress: Optional[ProgressCallback] = None):
        self.load()
        if progress:
            progress(0.15, "running Hunyuan3D shape diffusion")
        mesh = self._shape_pipe(
            image=image,
            num_inference_steps=opts.num_inference_steps,
            guidance_scale=opts.guidance_scale,
            octree_resolution=opts.octree_resolution,
        )[0]
        if opts.with_texture and self._tex_pipe is not None:
            if progress:
                progress(0.65, "painting texture")
            mesh = self._tex_pipe(mesh, image=image)
        return mesh


# ---------------------------------------------------------------------------
# Public pipeline — sync core + async wrapper
# ---------------------------------------------------------------------------

class PlushyPipeline:
    """Singleton-friendly image→GLB pipeline with async interface."""

    def __init__(self, output_dir: Path | str = "outputs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if MOCK:
            self._backend = None
            log.warning("PLUSHY_MOCK=1 — placeholder meshes, no model loaded")
        elif BACKEND == "hunyuan3d":
            self._backend = _HunyuanBackend()
        else:
            self._backend = _TrellisBackend()

    # -- synchronous core (runs in thread pool) -------------------------
    def generate_sync(self, image_path: Path, opts: GenerationOptions,
                      job_id: Optional[str] = None,
                      progress: Optional[ProgressCallback] = None) -> GenerationResult:
        t0 = time.time()
        job_id = job_id or uuid.uuid4().hex[:12]

        if progress:
            progress(0.05, "preprocessing image")
        image = load_and_preprocess_image(
            image_path, remove_bg=opts.remove_background)

        if MOCK:
            if progress:
                progress(0.5, "mock generation")
            time.sleep(1.0)  # simulate work
            mesh = _mock_mesh()
        else:
            mesh = self._backend.generate(image, opts, progress)

        if progress:
            progress(0.85, "cleaning mesh & exporting GLB")
        out_path = self.output_dir / f"{job_id}.glb"
        vcount, fcount = clean_and_export_glb(
            mesh, out_path,
            simplify_ratio=opts.simplify_ratio,
            with_texture=opts.with_texture,
        )
        if progress:
            progress(1.0, "done")
        return GenerationResult(
            glb_path=out_path,
            elapsed_sec=time.time() - t0,
            vertex_count=vcount,
            face_count=fcount,
            seed_used=opts.seed,
        )

    # -- async wrapper (never blocks the event loop) --------------------
    async def generate(self, image_path: Path, opts: GenerationOptions,
                       job_id: Optional[str] = None,
                       progress: Optional[ProgressCallback] = None) -> GenerationResult:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _executor, self.generate_sync, image_path, opts, job_id, progress)

    def warmup(self):
        """Pre-load model weights (call at server startup)."""
        if MOCK or self._backend is None:
            return
        try:
            self._backend.load()
        except Exception as e:
            log.error("warmup failed: %s", e)


# Convenience singleton
_pipeline: Optional[PlushyPipeline] = None

def get_pipeline(output_dir: Path | str = "outputs") -> PlushyPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = PlushyPipeline(output_dir=output_dir)
    return _pipeline
