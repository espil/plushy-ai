"""Plushy-AI 2.0 Reference Analyzer and region selection (Phase 2).

Library-level only: there is no server or UI wiring in this package
(Phase 6 wires it into the Studio). Everything here uses Pillow plus the
Python standard library, and reuses the Phase 1 Asset Standard Engine
(`asset_standard.analyze_file`) instead of duplicating it.

Rules (Plushy-AI 2.0 development prompt, Phase 2):
  - Uploads are validated by size, extension AND actual content
    (magic bytes plus Pillow format verification). Extension alone is
    never trusted.
  - Server-side filenames are generated safe IDs only. A user-supplied
    filename is kept as metadata and never used in any path.
  - An automatically suggested mask is only a suggestion. No area is a
    generation target until a user confirms a mask.
  - Original files are read-only and never modified.
"""

from .upload import (
    CATEGORIES,
    DEFAULT_MAX_BYTES,
    ReferenceError,
    detect_format,
    generate_reference_id,
    safe_storage_name,
    validate_category,
    validate_upload,
)
from .analyze import REFERENCE_SCHEMA_VERSION, analyze_reference, ingest_reference
from .mask import (
    MaskCanvas,
    build_mask_record,
    generation_target,
    load_mask,
    save_mask,
    suggest_mask,
)

__all__ = [
    "CATEGORIES",
    "DEFAULT_MAX_BYTES",
    "REFERENCE_SCHEMA_VERSION",
    "MaskCanvas",
    "ReferenceError",
    "analyze_reference",
    "build_mask_record",
    "detect_format",
    "generate_reference_id",
    "generation_target",
    "ingest_reference",
    "load_mask",
    "safe_storage_name",
    "save_mask",
    "suggest_mask",
    "validate_category",
    "validate_upload",
]
