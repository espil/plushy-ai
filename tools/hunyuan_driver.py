"""
tools/hunyuan_driver.py - Hunyuan3D quality-backend driver.

Runs INSIDE the Hunyuan venv (/opt/hunyuan-venv) as a subprocess of
pipeline_3d.Model3DPipeline (backend="hunyuan"); never imported by
the app python. Loads the Hunyuan3D-2mini shape pipeline and the
Hunyuan3D-2.0 paint pipeline from the local HF cache (the caller
sets HF_HUB_OFFLINE=1 after prefetch verified the cache), generates
a mesh from one image, bakes a real texture onto it, and exports a
textured GLB.

Memory arrangement (the whole point of this backend's settings):
the target PC has 8 GB VRAM and 16 GB system RAM, so both pipelines
run with diffusers model CPU offload - one module at a time lives
on the GPU, the rest waits in RAM. The shape stage is fully
released before paint loads. This is slow (minutes per model) and
the prints below keep every stage visible in the caller's streamed
log; a silent stall is the failure this codebase designs against.

    python tools/hunyuan_driver.py --image in.png --out out.glb \
        --shape-model tencent/Hunyuan3D-2mini \
        --paint-model tencent/Hunyuan3D-2 \
        --octree-resolution 256 --steps 30 \
        --render-resolution 512 --texture-size 1024

Exit code 0 = GLB written; anything else fails loudly via traceback.
"""

from __future__ import annotations

import argparse
import gc
import sys
import time


def log(msg: str) -> None:
    print(f"[hunyuan] {msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--shape-model", default="tencent/Hunyuan3D-2mini")
    ap.add_argument("--paint-model", default="tencent/Hunyuan3D-2")
    ap.add_argument("--octree-resolution", type=int, default=256)
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--render-resolution", type=int, default=512)
    ap.add_argument("--texture-size", type=int, default=1024)
    args = ap.parse_args()

    import torch
    from PIL import Image

    log(f"torch {torch.__version__}, cuda={torch.cuda.is_available()}")
    if not torch.cuda.is_available():
        log("FAIL: CUDA is not available to the Hunyuan venv - the "
            "quality backend cannot run on CPU in any honest time. "
            "Check the container was started with --gpus all.")
        return 1
    props = torch.cuda.get_device_properties(0)
    log(f"device {props.name}, VRAM {props.total_memory / 2**30:.1f} GiB")

    image = Image.open(args.image).convert("RGB")

    # -- shape stage -------------------------------------------------
    from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline

    t0 = time.time()
    log(f"loading shape pipeline {args.shape_model} (CPU offload on)")
    shape = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
        args.shape_model)
    if hasattr(shape, "enable_model_cpu_offload"):
        shape.enable_model_cpu_offload()
    log(f"generating mesh (steps={args.steps}, "
        f"octree={args.octree_resolution}) ...")
    mesh = shape(image=image,
                 num_inference_steps=args.steps,
                 octree_resolution=args.octree_resolution)[0]
    log(f"shape done in {time.time() - t0:.0f}s: "
        f"{len(mesh.vertices)} vertices, {len(mesh.faces)} faces")
    del shape
    gc.collect()
    torch.cuda.empty_cache()

    # -- paint stage ---------------------------------------------------
    from hy3dgen.texgen import Hunyuan3DPaintPipeline

    t0 = time.time()
    log(f"loading paint pipeline {args.paint_model} (CPU offload on)")
    paint = Hunyuan3DPaintPipeline.from_pretrained(args.paint_model)
    if hasattr(paint, "enable_model_cpu_offload"):
        paint.enable_model_cpu_offload()
    log(f"baking texture (render={args.render_resolution}, "
        f"texture={args.texture_size}) ...")
    try:
        mesh = paint(mesh, image=image,
                     render_resolution=args.render_resolution,
                     texture_size=args.texture_size)
    except TypeError:
        # The pinned hy3dgen build rejected the resolution kwargs:
        # fall back to the paint pipeline's own config defaults and
        # SAY SO in the log (never silent) - the bake still happens,
        # at whatever resolution the installed config carries.
        log("paint resolution kwargs rejected by this hy3dgen build; "
            "retrying with the pipeline's config defaults")
        mesh = paint(mesh, image=image)
    log(f"paint done in {time.time() - t0:.0f}s")
    del paint
    gc.collect()
    torch.cuda.empty_cache()

    mesh.export(args.out)
    log(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
