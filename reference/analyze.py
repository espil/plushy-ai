"""Reference ingestion and analysis (Phase 2).

Ingestion validates the upload (see upload.py), stores it under a
generated safe ID, analyzes the stored copy with the Phase 1 Asset
Standard Engine (imported, not duplicated), and emits a reference
record that preserves the link between the analysis and the original
image: original filename, stored safe filename, format, size, sha256,
reference ID, and the full Phase 1 asset-standard dict.

A fresh reference record always has `mask: None` and
`generation_target: None`: nothing is a generation target until a user
confirms a mask (see mask.py).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from asset_standard import analyze_file

from .upload import (
    DEFAULT_MAX_BYTES,
    ReferenceError,
    generate_reference_id,
    safe_storage_name,
    validate_category,
    validate_upload,
)

REFERENCE_SCHEMA_VERSION = "1.0"


def _record(reference_id: str, original_filename: str, stored_name: str,
            fmt: str, data: bytes, category, standard: dict) -> dict:
    return {
        "schema_version": REFERENCE_SCHEMA_VERSION,
        "reference_id": reference_id,
        "source": {
            "original_filename": str(original_filename),
            "stored_filename": stored_name,
            "format": fmt,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        "category": category,
        "asset_standard": standard,
        # Linkage back to the Phase 1 record for the same bytes.
        "analysis_asset_id": standard.get("asset_id"),
        "analysis_sha256": standard.get("source", {}).get("sha256"),
        "mask": None,
        "generation_target": None,
    }


def analyze_reference(path, original_filename=None, category=None,
                      reference_id=None) -> dict:
    """Analyze an existing on-disk image file (read-only) into a record.

    The file's bytes are validated exactly like an upload (extension
    plus content), so a mislabeled file is rejected here too.
    """
    path = Path(path)
    if not path.exists():
        raise ReferenceError(f"file not found: {path}")
    data = path.read_bytes()
    original = original_filename if original_filename is not None \
        else path.name
    info = validate_upload(original, data)
    if category is not None:
        validate_category(category)
    standard = analyze_file(path)
    rid = reference_id or generate_reference_id()
    return _record(rid, original, path.name, info["format"], data,
                   category, standard)


def ingest_reference(data: bytes, original_filename: str, storage_dir,
                     category=None,
                     max_bytes: int = DEFAULT_MAX_BYTES) -> dict:
    """Validate, store, and analyze one uploaded reference image.

    Writes two files into `storage_dir`: the image under its generated
    safe name, and `<reference_id>.reference.json`. The user-supplied
    filename never appears in any written path. Returns the record.
    """
    info = validate_upload(original_filename, data, max_bytes=max_bytes)
    if category is not None:
        validate_category(category)

    reference_id = generate_reference_id()
    stored_name = safe_storage_name(reference_id, info["format"])
    storage = Path(storage_dir)
    storage.mkdir(parents=True, exist_ok=True)
    dest = storage / stored_name
    # Defense in depth: the resolved destination must stay inside the
    # storage directory.
    if dest.resolve().parent != storage.resolve():
        raise ReferenceError("storage path escapes the storage directory")
    dest.write_bytes(data)

    standard = analyze_file(dest)
    record = _record(reference_id, original_filename, stored_name,
                     info["format"], data, category, standard)
    (storage / f"{reference_id}.reference.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return record
