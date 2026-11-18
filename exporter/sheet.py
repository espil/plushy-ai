"""PNG sprite sheet packing - Plushy-AI 2.0 Phase 5.

Packs the 8 per-direction PNGs into one sheet with a fixed, documented
grid layout:

    columns = 4, rows = 2, directions in canonical order
    (S, SE, E, NE, N, NW, W, SW) left-to-right, top row first:

        S   SE  E   NE
        N   NW  W   SW

Every cell is exactly the shared canvas size. A direction that is
missing or failed validation keeps its cell fully transparent - its
place in the grid is never collapsed and no other direction is shifted
into it. The packing result reports, per direction, whether it was
packed and its cell coordinates.
"""
from __future__ import annotations

from pathlib import Path

DIRECTIONS = ("S", "SE", "E", "NE", "N", "NW", "W", "SW")
SHEET_COLUMNS = 4
SHEET_ROWS = 2


def cell_origin(direction: str, cell_width: int, cell_height: int):
    """Top-left (x, y) of a direction's cell in the sheet."""
    idx = DIRECTIONS.index(direction)
    return (idx % SHEET_COLUMNS) * cell_width, \
        (idx // SHEET_COLUMNS) * cell_height


def pack_sprite_sheet(images, cell_size, out_path):
    """Pack direction images into one sheet PNG.

    `images` maps direction -> PIL.Image (or None). Only directions
    present with an image whose size equals `cell_size` are drawn;
    anything else leaves its cell transparent and is reported as not
    packed. Returns (sheet_path, {direction: {"packed": bool,
    "cell": {"x","y","width","height"}}}).

    Images are drawn as-is (alpha-composited at the cell origin);
    nothing is resized.
    """
    from PIL import Image

    cell_w, cell_h = cell_size
    sheet = Image.new("RGBA", (SHEET_COLUMNS * cell_w, SHEET_ROWS * cell_h),
                      (0, 0, 0, 0))
    placement = {}
    for direction in DIRECTIONS:
        x, y = cell_origin(direction, cell_w, cell_h)
        entry = {"packed": False,
                 "cell": {"x": x, "y": y, "width": cell_w, "height": cell_h}}
        img = images.get(direction)
        if img is not None and img.size == (cell_w, cell_h):
            sheet.alpha_composite(img.convert("RGBA"), (x, y))
            entry["packed"] = True
        placement[direction] = entry
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path, placement
