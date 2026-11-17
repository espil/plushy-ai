"""Mask creation, editing, suggestion, and records (Phase 2).

Mask convention (documented in docs/REFERENCE_WORKFLOW.md):
  A mask is a single-channel selection the size of the reference image.
  Saved as a transparent PNG, mask-area pixels are opaque white
  (255, 255, 255, 255) and every other pixel is fully transparent
  (0, 0, 0, 0). When loaded back, alpha > 0 means "in the mask".

Generation-target rule: a mask record's `generation_target` is None
unless the mask is BOTH user-confirmed (`confirmed=True`) AND
non-empty. An automatic suggestion is never confirmed by construction:
`suggest_mask` always returns an unconfirmed mask.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from .upload import ReferenceError, validate_category

MASK_RECORD_SCHEMA_VERSION = "1.0"


class MaskCanvas:
    """An editable mask the exact size of its reference image.

    Pixel storage is a Pillow "L" image: 255 = in mask, 0 = not.
    """

    def __init__(self, width: int, height: int):
        from PIL import Image

        if width <= 0 or height <= 0:
            raise ReferenceError(
                f"mask size must be positive, got {width}x{height}")
        self.width = width
        self.height = height
        self._img = Image.new("L", (width, height), 0)

    # -- size ------------------------------------------------------------
    def validate_size(self, width: int, height: int) -> None:
        """Raise unless this mask exactly matches the given image size."""
        if (self.width, self.height) != (width, height):
            raise ReferenceError(
                f"mask size {self.width}x{self.height} does not match "
                f"reference image size {width}x{height}")

    # -- editing -----------------------------------------------------------
    def _check_rect(self, x, y, width, height) -> None:
        if width <= 0 or height <= 0:
            raise ReferenceError("rectangle must have positive size")
        if x < 0 or y < 0 or x + width > self.width or \
                y + height > self.height:
            raise ReferenceError(
                f"rectangle ({x}, {y}, {width}x{height}) lies outside "
                f"the {self.width}x{self.height} mask")

    def add_rectangle(self, x: int, y: int, width: int, height: int):
        """Add a rectangle to the mask (user edit operation)."""
        from PIL import ImageDraw

        self._check_rect(x, y, width, height)
        ImageDraw.Draw(self._img).rectangle(
            [x, y, x + width - 1, y + height - 1], fill=255)
        return self

    def remove_rectangle(self, x: int, y: int, width: int, height: int):
        """Remove a rectangle from the mask (user edit operation)."""
        from PIL import ImageDraw

        self._check_rect(x, y, width, height)
        ImageDraw.Draw(self._img).rectangle(
            [x, y, x + width - 1, y + height - 1], fill=0)
        return self

    def clear(self):
        """Remove everything from the mask."""
        from PIL import Image

        self._img = Image.new("L", (self.width, self.height), 0)
        return self

    # -- queries -----------------------------------------------------------
    def is_empty(self) -> bool:
        return self._img.getbbox() is None

    def bounds(self) -> dict | None:
        """Bounding box {x, y, width, height} of the mask, or None."""
        bbox = self._img.getbbox()
        if bbox is None:
            return None
        return {"x": bbox[0], "y": bbox[1],
                "width": bbox[2] - bbox[0], "height": bbox[3] - bbox[1]}

    def pixel_count(self) -> int:
        return sum(1 for v in self._img.getdata() if v)

    # -- transparent PNG form ---------------------------------------------
    def to_transparent_png_bytes(self) -> bytes:
        """Encode per the documented convention (opaque white = mask)."""
        from PIL import Image

        rgba = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        white = Image.new("RGBA", (self.width, self.height),
                           (255, 255, 255, 255))
        rgba.paste(white, (0, 0), self._img)
        buf = io.BytesIO()
        rgba.save(buf, format="PNG")
        return buf.getvalue()

    @classmethod
    def from_transparent_png_bytes(cls, data: bytes,
                                   expected_size=None) -> "MaskCanvas":
        """Load a mask saved with the documented convention."""
        from PIL import Image

        try:
            with Image.open(io.BytesIO(data)) as img:
                img.load()
                rgba = img.convert("RGBA")
        except Exception as e:  # noqa: BLE001
            raise ReferenceError(f"cannot decode mask PNG: {e}") from e
        mask = cls(rgba.width, rgba.height)
        if expected_size is not None:
            mask.validate_size(*expected_size)
        mask._img = rgba.getchannel("A").point(lambda a: 255 if a else 0)
        return mask


def load_mask(path, expected_size=None) -> MaskCanvas:
    """Load a transparent-PNG mask from disk."""
    path = Path(path)
    if not path.exists():
        raise ReferenceError(f"mask file not found: {path}")
    return MaskCanvas.from_transparent_png_bytes(path.read_bytes(),
                                                 expected_size)


def suggest_mask(reference_record: dict) -> MaskCanvas:
    """Propose a mask from the reference's non-transparent content bounds.

    SUGGESTION ONLY: the returned mask is unconfirmed, and callers must
    not treat it as a generation target until a user edits/confirms it
    and a record is built with confirmed=True. A fully transparent or
    bound-less analysis yields an empty suggestion.
    """
    standard = reference_record.get("asset_standard") or {}
    canvas = standard.get("canvas") or {}
    width, height = canvas.get("width"), canvas.get("height")
    if not width or not height:
        raise ReferenceError(
            "reference record has no canvas size; cannot suggest a mask")
    mask = MaskCanvas(width, height)
    bounds = standard.get("content_bounds")
    if bounds:
        mask.add_rectangle(bounds["x"], bounds["y"],
                           bounds["width"], bounds["height"])
    return mask


def generation_target(mask_record: dict | None) -> dict | None:
    """Return the generation target for a mask record, or None.

    None unless the record is user-confirmed and non-empty. This is the
    single gate Phase 3 must call before generating anything.
    """
    if not mask_record or not mask_record.get("confirmed"):
        return None
    bounds = mask_record.get("bounds")
    if not bounds:
        return None
    return {
        "reference_id": mask_record["reference_id"],
        "category": mask_record["category"],
        "bounds": bounds,
        "mask_sha256": mask_record["mask_sha256"],
    }


def build_mask_record(reference_record: dict, mask: MaskCanvas,
                      confirmed: bool = False,
                      category=None) -> dict:
    """Build the mask metadata record linking mask, reference, category.

    The mask size must exactly match the reference image size. The
    category defaults to the reference record's category and is
    validated against the Phase 2 set either way.
    """
    standard = reference_record.get("asset_standard") or {}
    canvas = standard.get("canvas") or {}
    if not canvas.get("width") or not canvas.get("height"):
        raise ReferenceError("reference record has no canvas size")
    mask.validate_size(canvas["width"], canvas["height"])

    cat = category if category is not None \
        else reference_record.get("category")
    if cat is not None:
        validate_category(cat)

    png = mask.to_transparent_png_bytes()
    record = {
        "schema_version": MASK_RECORD_SCHEMA_VERSION,
        "reference_id": reference_record["reference_id"],
        "category": cat,
        "width": mask.width,
        "height": mask.height,
        "bounds": mask.bounds(),
        "pixel_count": mask.pixel_count(),
        "confirmed": bool(confirmed),
        "mask_sha256": hashlib.sha256(png).hexdigest(),
        "reference_sha256": reference_record.get("source", {}).get("sha256"),
    }
    record["generation_target"] = generation_target(record)
    return record


def save_mask(mask: MaskCanvas, path, reference_record: dict,
              confirmed: bool = False, category=None) -> dict:
    """Save a mask as a transparent PNG plus its metadata JSON.

    Writes `path` (the PNG) and `path` with a .json suffix (the record
    from build_mask_record). Returns the record. The mask size is
    validated against the reference before anything is written.
    """
    record = build_mask_record(reference_record, mask,
                               confirmed=confirmed, category=category)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(mask.to_transparent_png_bytes())
    meta = path.with_suffix(".json")
    record["mask_filename"] = path.name
    meta.write_text(json.dumps(record, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return record
