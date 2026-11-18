"""Plushy-AI 2.0 Aseprite Bridge / Export (Phase 5).

Library + CLI only: no server or UI wiring in this package (Phase 6
wires it into the Studio). Reuses by importing - never modifying -
the Phase 1 Asset Standard Engine (`asset_standard.analyze_file`,
for measured validation facts and for the mandatory .aseprite
round-trip check). The Aseprite writer is a new, minimal writer
built on the published Aseprite file format (stdlib struct/zlib);
no Aseprite CLI or other external tool is used.

Rules (Plushy-AI 2.0 development prompt, Phase 5):
  - PNG export works independently of the .aseprite export.
  - All 8 directions are always accounted for in the manifest
    (ok / missing / needs_review); nothing is silently dropped and
    nothing is resized to fit.
  - A layered .aseprite is only reported as supported because the
    writer's output round-trips through the Phase 1 analyzer;
    real-Aseprite opening is unverified (Aseprite is not installed
    in this environment).
  - A source Aseprite standard record, when supplied, is embedded
    in the export manifest in full with its sha256, so the original
    metadata is preserved through the export path.
  - Originals are read-only; outputs go to a separate directory.
"""

from .aseprite_write import AsepriteWriteError, write_aseprite
from .export import MANIFEST_SCHEMA_VERSION, ExportError, export_assets, \
    validate_image
from .sheet import DIRECTIONS, SHEET_COLUMNS, SHEET_ROWS, pack_sprite_sheet

__all__ = [
    "AsepriteWriteError",
    "DIRECTIONS",
    "MANIFEST_SCHEMA_VERSION",
    "SHEET_COLUMNS",
    "SHEET_ROWS",
    "ExportError",
    "export_assets",
    "pack_sprite_sheet",
    "validate_image",
    "write_aseprite",
]
