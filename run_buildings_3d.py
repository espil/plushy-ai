"""
run_buildings_3d.py - batch-produce the Waitemata building GLBs.

Reads buildings_3d_manifest.json and converts every source image in
inputs/buildings_iso/ into outputs/models3d/<asset>.glb through the
Plushy 3D pipeline (SF3D + the building spec: low-poly budget, real
textures at 1024, gltfpack compression - all enforced in pipeline_3d).

Resumable: an asset whose GLB and sidecar JSON already exist is
skipped, so re-running continues where a previous run stopped
(--force redoes everything). One failure never stops the batch; the
final summary lists failures with their reasons, and the exit code is
1 if anything failed (0 = all done or skipped).

Run inside the Docker image - run-buildings-3d.bat does that:
    python run_buildings_3d.py [--only wm_b04_family_house,...] [--force]

Output folder: $PLUSHY_OUTPUT_DIR/models3d when the variable is set
(the launcher sets it), otherwise ./outputs/models3d.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from pipeline_3d import Model3DOptions, Model3DPipeline  # noqa: E402

NORMAL_BUDGET = 8000
LANDMARK_BUDGET = 20000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(BASE / "buildings_3d_manifest.json"))
    ap.add_argument("--inputs", default=str(BASE / "inputs" / "buildings_iso"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--only", default=None, help="comma-separated asset names")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--texture", type=int, default=1024, choices=(512, 1024, 2048),
                    help="SF3D texture resolution (v2 batches use 2048)")
    args = ap.parse_args()

    out_dir = Path(args.out) if args.out else (
        Path(os.getenv("PLUSHY_OUTPUT_DIR", BASE / "outputs")) / "models3d")
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    inputs = Path(args.inputs).resolve()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    assets = manifest["assets"]
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        assets = [a for a in assets if a["asset"] in wanted]

    pipe = Model3DPipeline()
    done, skipped, failed = [], [], []
    t_start = time.time()
    for i, entry in enumerate(assets, 1):
        asset = entry["asset"]
        src = inputs / entry["source"]
        dest = out_dir / f"{asset}.glb"
        sidecar = Path(str(dest) + ".json")
        tag = f"[{i}/{len(assets)}] {asset}"
        if dest.exists() and sidecar.exists() and not args.force:
            print(f"{tag}: SKIP (already produced)", flush=True)
            skipped.append(asset)
            continue
        if not src.exists():
            print(f"{tag}: FAILED - source image missing: {src}", flush=True)
            failed.append((asset, "source image missing"))
            continue
        budget = LANDMARK_BUDGET if entry.get("landmark") else NORMAL_BUDGET
        t0 = time.time()
        try:
            actual, stats = pipe.image_to_glb(
                src, dest,
                Model3DOptions(texture_resolution=args.texture, tri_budget=budget),
                progress=lambda p, m: print(f"{tag}: {p:.0%} {m}", flush=True))
            print(f"{tag}: DONE {actual.name} - {stats['triangles']} tris, "
                  f"{stats['bytes'] // 1024} KB, {time.time() - t0:.0f}s", flush=True)
            done.append(asset)
        except Exception as e:
            print(f"{tag}: FAILED - {type(e).__name__}: {e}", flush=True)
            failed.append((asset, f"{type(e).__name__}: {e}"))

    print()
    print(f"=== building batch summary ({time.time() - t_start:.0f}s) ===")
    print(f"done: {len(done)}  skipped: {len(skipped)}  failed: {len(failed)}")
    for asset, why in failed:
        print(f"  FAILED {asset}: {why}")
    print(f"GLBs are in: {out_dir}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
