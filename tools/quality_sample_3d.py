"""
tools/quality_sample_3d.py - REAL quality-backend sample generation.

Converts three bundled Waitemata building images (the pipeline's
standard production inputs) to textured GLBs through the Studio 2.0
service layer - Studio2Service.submit_model3d with backend
"hunyuan", the exact wiring a 2.0 model3d job uses - and checks
every output with the production gate (pipeline_3d.validate_glb).
Prints QUALITY SAMPLE PASS only when all three are real textured
meshes whose sidecars honestly say engine=hunyuan3d, mock=false.

Run inside the Docker image with the GPU (run-quality-sample.bat
does that on Windows as the last step of the unattended run):
    python tools/quality_sample_3d.py

Exit code 0 = PASS, 1 = FAIL. Refuses to run under PLUSHY_MOCK=1:
a stamped placeholder proves nothing about the quality backend.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]

# Standard test objects: three ordinary bundled building inputs
# (deterministic picks from inputs/waitemata_v2, the same set the
# SF3D building batches convert).
TEST_IMAGES = [
    "inputs/waitemata_v2/b02_storyteller_cottage.jpg",
    "inputs/waitemata_v2/b04_family_house.jpg",
    "inputs/waitemata_v2/b05_house_honey.jpg",
]


def main() -> int:
    from pipeline_3d import MOCK, validate_glb

    if MOCK:
        print("[quality-sample] PLUSHY_MOCK=1 is set - this run can "
              "only produce stamped placeholders, which prove "
              "nothing. FAIL.")
        return 1

    from studio2 import Studio2Service

    root = REPO / "outputs" / "quality_sample"
    svc = Studio2Service(root)
    refs = root / "references"
    failures = []
    for rel in TEST_IMAGES:
        src = REPO / rel
        name = src.name
        print(f"[quality-sample] {name}: converting (quality "
              "backend; minutes, not seconds) ...", flush=True)
        if not src.exists():
            print(f"[quality-sample] {name}: FAIL - bundled input "
                  f"missing: {rel}")
            failures.append(name)
            continue
        shutil.copyfile(src, refs / name)
        try:
            view = svc.submit_model3d({
                "source": f"references/{name}",
                "backend": "hunyuan",
                "tri_budget": 8000,
                "texture_resolution": 1024,
            })
        except Exception as e:
            print(f"[quality-sample] {name}: FAIL - "
                  f"{type(e).__name__}: {e}")
            failures.append(name)
            continue
        if view["status"] != "completed":
            print(f"[quality-sample] {name}: FAIL - job status "
                  f"{view['status']}: {view.get('error')}")
            failures.append(name)
            continue
        result = view["result"]
        glb = root / result["output_files"][0]
        try:
            checked = validate_glb(glb)
        except Exception as e:
            print(f"[quality-sample] {name}: FAIL - gate: {e}")
            failures.append(name)
            continue
        sidecar = json.loads(
            Path(str(glb) + ".json").read_text(encoding="utf-8"))
        honest = (sidecar.get("engine") == "hunyuan3d"
                  and sidecar.get("backend") == "hunyuan"
                  and sidecar.get("mock") is False)
        print(f"[quality-sample] {name}: bytes={checked['bytes']} "
              f"triangles={checked['triangles']} "
              f"images={checked['images']} "
              f"engine={sidecar.get('engine')} "
              f"mock={sidecar.get('mock')} sidecar_honest={honest}")
        if not honest:
            print(f"[quality-sample] {name}: FAIL - sidecar does "
                  "not honestly label the quality backend")
            failures.append(name)

    if failures:
        print(f"[quality-sample] QUALITY SAMPLE FAIL - "
              f"{len(failures)}/{len(TEST_IMAGES)} objects failed: "
              f"{failures}")
        return 1
    print("[quality-sample] QUALITY SAMPLE PASS - 3 real textured "
          "meshes from the Hunyuan quality backend.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
