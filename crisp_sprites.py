#!/usr/bin/env python3
"""Binarize the alpha channel of existing sprite PNGs.

Removes semi-transparent fringe pixels (the ghostly edges rembg leaves)
without re-generating: every pixel becomes fully opaque or fully
transparent. Only touches images that actually have partial alpha.

Usage (Windows PowerShell, in the repo dir):
    python crisp_sprites.py ./city_sprites ./char_sprites
"""
import sys
from pathlib import Path


def crisp_file(path: Path, thresh: int = 127) -> bool:
    import numpy as np
    from PIL import Image
    img = Image.open(path)
    if img.mode not in ("RGBA", "LA"):
        return False
    arr = np.array(img.convert("RGBA"))
    a = arr[:, :, 3]
    if not ((a > 0) & (a < 255)).any():
        return False  # already crisp
    arr[:, :, 3] = np.where(a > thresh, 255, 0).astype(np.uint8)
    Image.fromarray(arr).save(path)
    return True


def main() -> None:
    dirs = sys.argv[1:] or ["."]
    fixed = skipped = 0
    for d in dirs:
        for p in Path(d).rglob("*.png"):
            try:
                if crisp_file(p):
                    fixed += 1
                else:
                    skipped += 1
            except Exception as e:  # noqa: BLE001
                print(f"skip {p}: {e}")
    print(f"crisped {fixed} images, {skipped} already crisp")


if __name__ == "__main__":
    main()
