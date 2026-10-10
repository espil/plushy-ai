#!/usr/bin/env python3
"""
Plushy AI — batch mode (CLI).

Point it at a folder of YOUR OWN original concept art, get back a folder of GLBs:

    python batch.py --input ./my_art --output ./my_glbs

Each image becomes <name>.glb, plus a manifest.json with per-file results.
Runs sequentially (one GPU at a time). Use --skip-existing to resume an
interrupted run without redoing finished files.

    python batch.py --input ./my_art --output ./my_glbs --seed 42 --steps 20
    python batch.py --input ./my_art --output ./my_glbs --skip-existing
    PLUSHY_MOCK=1 python batch.py --input ./my_art --output ./my_glbs   # no GPU
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Plushy AI batch: images → GLBs")
    p.add_argument("--input", "-i", required=True,
                   help="folder of input images (your own original art)")
    p.add_argument("--output", "-o", required=True,
                   help="folder for .glb outputs (created if missing)")
    p.add_argument("--seed", type=int, default=0,
                   help="base seed; file N uses seed+N (default: 0)")
    p.add_argument("--quality", choices=["draft", "balanced", "detailed"],
                   default=None,
                   help="quality preset: draft (fast) / balanced (default) / detailed (slow, more VRAM)")
    p.add_argument("--steps", type=int, default=None,
                   help="diffusion inference steps (overrides --quality)")
    p.add_argument("--guidance", type=float, default=7.5,
                   help="guidance scale, Hunyuan3D backend (default: 7.5)")
    p.add_argument("--octree", type=int, default=None,
                   help="octree resolution, Hunyuan3D backend (overrides --quality)")
    p.add_argument("--simplify", type=float, default=None,
                   help="mesh decimation ratio 0-1 (overrides --quality)")
    p.add_argument("--no-texture", action="store_true",
                   help="skip texture painting (geometry only)")
    p.add_argument("--no-bg-remove", action="store_true",
                   help="skip rembg background removal")
    p.add_argument("--skip-existing", action="store_true",
                   help="skip images whose .glb already exists in output")
    p.add_argument("--mock", action="store_true",
                   help="placeholder meshes, no GPU/weights (same as PLUSHY_MOCK=1)")
    p.add_argument("--recursive", "-r", action="store_true",
                   help="scan input folder recursively")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.mock:
        os.environ["PLUSHY_MOCK"] = "1"

    # Import AFTER env is set (pipeline reads PLUSHY_MOCK at import time)
    from pipeline_3d import (GenerationOptions, apply_quality_preset,
                          get_pipeline)

    # Opt-in low-VRAM mode for 8GB GPUs: no-op unless PLUSHY_LOWVRAM=1
    try:
        import lowvram_patch
        if lowvram_patch.apply_lowvram():
            print("low-VRAM mode active (PLUSHY_LOWVRAM=1)")
    except Exception as e:
        print(f"lowvram patch skipped: {e}")

    # Resolve quality preset -> knobs (explicit flags win over preset)
    from pipeline_3d import QUALITY_PRESETS
    preset = QUALITY_PRESETS.get((args.quality or "balanced").lower(),
                                 QUALITY_PRESETS["balanced"])
    steps = args.steps if args.steps is not None else preset["num_inference_steps"]
    octree = args.octree if args.octree is not None else preset["octree_resolution"]
    simplify = args.simplify if args.simplify is not None else preset["simplify_ratio"]
    if args.quality:
        print(f"quality preset '{args.quality}': steps={steps} "
              f"octree={octree} simplify={simplify}")

    in_dir = Path(args.input)
    out_dir = Path(args.output)
    if not in_dir.is_dir():
        print(f"error: input is not a folder: {in_dir}", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)

    pattern = "**/*" if args.recursive else "*"
    files = sorted(
        f for f in in_dir.glob(pattern)
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS
    )
    if not files:
        print(f"error: no images ({', '.join(sorted(IMAGE_EXTS))}) found in {in_dir}",
              file=sys.stderr)
        return 2

    # --skip-existing: filter before we load any model
    if args.skip_existing:
        before = len(files)
        files = [f for f in files if not (out_dir / f"{f.stem}.glb").exists()]
        skipped = before - len(files)
        if skipped:
            print(f"skipping {skipped} already-generated file(s)")
    if not files:
        print("nothing to do — all outputs exist.")
        return 0

    print(f"Plushy batch: {len(files)} image(s) → {out_dir}")
    print(f"backend={os.getenv('PLUSHY_BACKEND', 'trellis')}"
          f" mock={os.getenv('PLUSHY_MOCK', '0') == '1'}")
    pipeline = get_pipeline(output_dir=out_dir)

    manifest: list[dict] = []
    ok, failed = 0, 0
    t_all = time.time()

    try:
        from tqdm import tqdm
        iterator = tqdm(enumerate(files), total=len(files), unit="img")
    except ImportError:
        iterator = enumerate(files)  # type: ignore[assignment]

    for i, img_path in iterator:
        job_id = f"batch-{int(time.time())}-{i:03d}"
        opts = GenerationOptions(
            seed=args.seed + i,
            num_inference_steps=steps,
            guidance_scale=args.guidance,
            octree_resolution=octree,
            simplify_ratio=simplify,
            with_texture=not args.no_texture,
            remove_background=not args.no_bg_remove,
        )
        entry: dict = {"input": str(img_path), "seed": opts.seed}
        try:
            res = pipeline.generate_sync(img_path, opts, job_id=job_id)
            # Rename to <stem>.glb for a clean asset folder
            final = out_dir / f"{img_path.stem}.glb"
            if res.glb_path != final:
                res.glb_path.replace(final)
            entry.update({
                "output": str(final),
                "status": "completed",
                "elapsed_sec": round(res.elapsed_sec, 1),
                "vertex_count": res.vertex_count,
                "face_count": res.face_count,
            })
            ok += 1
        except KeyboardInterrupt:
            entry.update({"status": "cancelled", "error": "interrupted by user"})
            manifest.append(entry)
            print("\ninterrupted — manifest saved for completed files.")
            break
        except Exception as e:  # noqa: BLE001 — keep going, record it
            entry.update({"status": "failed", "error": f"{type(e).__name__}: {e}"})
            failed += 1
        manifest.append(entry)

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    total = time.time() - t_all
    print(f"\ndone: {ok} ok, {failed} failed, {total:.0f}s total "
          f"({total / max(ok, 1):.1f}s/img)")
    print(f"manifest → {manifest_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
