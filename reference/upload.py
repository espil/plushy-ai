"""Upload validation, safe IDs, and category validation (Phase 2).

Validation layers, all required (extension alone is never enough):
  1. size limit,
  2. extension allow-list (.png / .jpg / .jpeg / .webp),
  3. magic-byte format detection,
  4. Pillow format verification (the decoded format must agree with
     both the extension and the magic bytes).

Server-side names come only from `generate_reference_id` plus a
canonical extension derived from the *detected* format. The original
user filename is metadata, never a path component.
"""

from __future__ import annotations

import io
import uuid

# Mirrors the 1.0 server's 20 MB upload cap (app.py /api/img2img).
DEFAULT_MAX_BYTES = 20 * 1024 * 1024

# Exactly the Phase 2 category set from the development prompt.
CATEGORIES = (
    "Hair", "Face", "Top", "Bottom", "One-piece",
    "Shoes", "Armor", "Weapon", "Accessory", "Effects",
)

_EXTENSION_FORMATS = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".webp": "WEBP",
}
_FORMAT_EXTENSIONS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}


class ReferenceError(Exception):
    """Raised when a reference upload, category, or mask is invalid."""


def validate_category(category) -> str:
    """Return `category` if it is in the Phase 2 set, else raise."""
    if category not in CATEGORIES:
        raise ReferenceError(
            f"unknown category {category!r}; must be one of: "
            + ", ".join(CATEGORIES))
    return category


def detect_format(data: bytes) -> str | None:
    """Detect PNG/JPEG/WEBP from magic bytes; None when unrecognized."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


def generate_reference_id() -> str:
    """Generate a safe server-side reference ID (no user input)."""
    return "ref_" + uuid.uuid4().hex


def safe_storage_name(reference_id: str, detected_format: str) -> str:
    """Build the on-disk filename from a generated ID + detected format.

    Raises ReferenceError if the ID is not one this module generated
    (defense in depth against ever letting a caller pass a raw
    user filename through as an ID).
    """
    if not reference_id.startswith("ref_") or \
            any(c not in "0123456789abcdef" for c in reference_id[4:]):
        raise ReferenceError(f"unsafe reference id: {reference_id!r}")
    try:
        ext = _FORMAT_EXTENSIONS[detected_format]
    except KeyError:
        raise ReferenceError(
            f"unsupported detected format: {detected_format!r}") from None
    return reference_id + ext


def validate_upload(original_filename: str, data: bytes,
                    max_bytes: int = DEFAULT_MAX_BYTES) -> dict:
    """Validate one uploaded reference image.

    Returns {"format", "extension", "size_bytes"} on success and raises
    ReferenceError on any mismatch, oversize, or undecodable content.
    `original_filename` is used only to read its extension; it is never
    used as a path.
    """
    from PIL import Image

    if not data:
        raise ReferenceError("empty upload")
    if len(data) > max_bytes:
        raise ReferenceError(
            f"upload too large: {len(data)} bytes (limit {max_bytes})")

    name = str(original_filename or "")
    dot = name.rfind(".")
    ext = name[dot:].lower() if dot >= 0 else ""
    if ext not in _EXTENSION_FORMATS:
        raise ReferenceError(
            f"unsupported extension {ext!r}; allowed: "
            + ", ".join(sorted(_EXTENSION_FORMATS)))
    expected = _EXTENSION_FORMATS[ext]

    detected = detect_format(data)
    if detected is None:
        raise ReferenceError(
            "unrecognized image content (no PNG/JPEG/WEBP signature)")
    if detected != expected:
        raise ReferenceError(
            f"extension/content mismatch: {ext} implies {expected} but "
            f"the file content is {detected}")

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
            pillow_format = img.format
    except Exception as e:  # noqa: BLE001 - surfaced as validation error
        raise ReferenceError(f"image content cannot be decoded: {e}") from e
    if pillow_format != detected:
        raise ReferenceError(
            f"decoder/format mismatch: Pillow reports {pillow_format}, "
            f"magic bytes indicate {detected}")

    return {"format": detected, "extension": ext, "size_bytes": len(data)}
