"""
tools/selftest_3d.py - end-to-end proof that the 3D pipeline is REAL.

Draws a simple house pictogram, runs it through the SF3D pipeline, and
checks the output with the same gate production jobs use
(pipeline_3d.validate_glb). Prints SELFTEST PASS only when the GLB is a
real textured mesh - many triangles, a non-degenerate bounding box, at
least one texture image. A gray sphere can never pass this test.

Run it inside the Docker image (selftest-3d.bat does that on Windows):
    python tools/selftest_3d.py

Exit code 0 = PASS, 1 = FAIL.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw  # noqa: E402


def draw_test_house(path: Path) -> None:
    im = Image.new("RGB", (768, 768), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([234, 360, 534, 640], fill=(196, 144, 92))            # walls
    d.polygon([(204, 360), (384, 190), (564, 360)], fill=(178, 64, 44))  # roof
    d.rectangle([344, 480, 424, 640], fill=(110, 72, 44))              # door
    d.rectangle([264, 410, 324, 470], fill=(150, 200, 230))            # window L
    d.rectangle([444, 410, 504, 470], fill=(150, 200, 230))            # window R
    im.save(path)


def main() -> int:
    from pipeline_3d import MOCK, Model3DPipeline, validate_glb

    root = Path(__file__).resolve().parents[1]
    out_dir = root / "outputs" / "selftest"
    out_dir.mkdir(parents=True, exist_ok=True)
    src = out_dir / "selftest_house.png"
    dest = out_dir / "selftest_house.glb"
    draw_test_house(src)
    print(f"[selftest] input image: {src}")

    if MOCK:
        print("[selftest] PLUSHY_MOCK=1 is set - this run can only produce a")
        print("[selftest] stamped placeholder, which proves nothing. FAIL.")
        return 1

    pipe = Model3DPipeline()
    try:
        actual, stats = pipe.image_to_glb(
            src, dest, progress=lambda p, m: print(f"[selftest] {p:.0%} {m}"))
        checked = validate_glb(actual)
    except Exception as e:
        print(f"[selftest] FAIL: {type(e).__name__}: {e}")
        return 1

    print(f"[selftest] output: {actual}")
    print(f"[selftest] bytes={checked['bytes']} triangles={checked['triangles']} "
          f"images={checked['images']} bbox_extents={checked['bbox_extents']}")
    print("[selftest] SELFTEST PASS - the pipeline produced a real textured mesh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
