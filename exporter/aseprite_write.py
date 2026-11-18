"""Minimal, real Aseprite (.aseprite) writer - Plushy-AI 2.0 Phase 5.

Writes files in the published Aseprite file format
(https://www.aseprite.org/docs/files/) - the same spec the Phase 1
analyzer (`asset_standard/analyze.py`) parses - using only the Python
standard library (struct + zlib). No Aseprite CLI or any other external
tool is involved.

Supported (and only this):
  - 32-bit RGBA color depth, one frame
  - image layers (type 0), visible + editable, normal blend, opacity 255
  - one compressed-image cel (type 2, zlib) per layer, at a caller-set
    position (default 0,0), holding the layer image's own pixels
  - layer names/order exactly as given

NOT written (see docs/ASEPRITE_IMPORT_EXPORT.md): multiple frames,
groups, tilemap layers, linked cels, tags, slices, user data, palettes,
color profiles, cel-extra / tileset chunks.

Verification boundary, stated plainly: files written here are proven by
round-tripping them through the Phase 1 analyzer (names, order, canvas,
frame count, cel geometry) and by byte-level format checks. Whether
real Aseprite opens them has NOT been verified in this environment -
Aseprite is not installed here.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

ASE_HEADER_SIZE = 128
ASE_HEADER_MAGIC = 0xA5E0
ASE_FRAME_MAGIC = 0xF1FA

CHUNK_LAYER = 0x2004
CHUNK_CEL = 0x2005

CEL_TYPE_COMPRESSED = 2
LAYER_TYPE_IMAGE = 0
LAYER_FLAGS_VISIBLE_EDITABLE = 0x03


class AsepriteWriteError(Exception):
    """Raised for invalid writer input (bad layer, bad canvas, ...)."""


def _string(s: str) -> bytes:
    raw = s.encode("utf-8")
    return struct.pack("<H", len(raw)) + raw


def _chunk(chunk_type: int, payload: bytes) -> bytes:
    return struct.pack("<IH", 6 + len(payload), chunk_type) + payload


def _layer_chunk(name: str) -> bytes:
    # Spec order: flags, type, child level, default width, default
    # height, blend mode, opacity, 3 reserved bytes, name string.
    payload = struct.pack("<HHHHH", LAYER_FLAGS_VISIBLE_EDITABLE,
                          LAYER_TYPE_IMAGE, 0, 0, 0)
    payload += struct.pack("<H", 0)      # blend mode: normal
    payload += struct.pack("<B", 255)    # opacity
    payload += b"\x00" * 3               # reserved
    payload += _string(name)
    return _chunk(CHUNK_LAYER, payload)


def _cel_chunk(layer_index: int, x: int, y: int, rgba_bytes: bytes,
               width: int, height: int) -> bytes:
    # Spec order: layer index, x, y, opacity, cel type, z-index,
    # 5 reserved bytes, width, height, zlib-compressed RGBA pixels
    # (row-major, top row first, 4 bytes per pixel).
    payload = struct.pack("<Hhh", layer_index, x, y)
    payload += struct.pack("<B", 255)               # opacity
    payload += struct.pack("<H", CEL_TYPE_COMPRESSED)
    payload += struct.pack("<h", 0)                 # z-index
    payload += b"\x00" * 5                          # reserved
    payload += struct.pack("<HH", width, height)
    payload += zlib.compress(rgba_bytes)
    return _chunk(CHUNK_CEL, payload)


def _frame(duration_ms: int, chunks: list[bytes]) -> bytes:
    body = b"".join(chunks)
    header = struct.pack("<IHHH", 16 + len(body), ASE_FRAME_MAGIC,
                         len(chunks), duration_ms)
    header += b"\x00" * 2
    header += struct.pack("<I", 0)  # new chunk count (used only if old=0xFFFF)
    return header + body


def _header(file_size: int, width: int, height: int) -> bytes:
    header = struct.pack("<IHHHHH", file_size, ASE_HEADER_MAGIC, 1,
                         width, height, 32)
    header += struct.pack("<I", 1)        # flags: layer opacity valid
    header += struct.pack("<H", 100)      # speed (deprecated)
    header += struct.pack("<I", 0) + struct.pack("<I", 0)
    header += struct.pack("<B", 0) + b"\x00" * 3   # transparent index + ignore
    header += struct.pack("<H", 0)        # number of colors (0 = 256, unused)
    header += struct.pack("<BB", 1, 1)    # pixel width / height
    header += struct.pack("<hhHH", 0, 0, 0, 0)     # grid x, y, width, height
    header += b"\x00" * (ASE_HEADER_SIZE - len(header))
    assert len(header) == ASE_HEADER_SIZE
    return header


def write_aseprite(path, layers, duration_ms: int = 100) -> Path:
    """Write a single-frame layered RGBA .aseprite file.

    `layers` is a list of (name, PIL.Image) pairs in bottom-to-top
    order; layer order and names are preserved exactly. Every layer
    image is converted to RGBA and written as one full-image cel at
    (0, 0) with the image's own width/height. All layer images must
    share one size, which becomes the canvas size - a mismatch raises
    AsepriteWriteError instead of silently resizing anything.

    Returns the output Path. Raises AsepriteWriteError on invalid input.
    """
    if not layers:
        raise AsepriteWriteError("at least one layer is required")
    prepared = []
    canvas = None
    seen = set()
    for name, img in layers:
        if not isinstance(name, str) or not name.strip():
            raise AsepriteWriteError("layer names must be non-empty strings")
        if name in seen:
            raise AsepriteWriteError(f"duplicate layer name: {name!r}")
        seen.add(name)
        rgba = img.convert("RGBA")
        if canvas is None:
            canvas = rgba.size
        elif rgba.size != canvas:
            raise AsepriteWriteError(
                f"layer {name!r} size {rgba.size} does not match canvas "
                f"{canvas}; layers are never resized")
        prepared.append((name, rgba))
    width, height = canvas

    chunks = [_layer_chunk(name) for name, _ in prepared]
    for idx, (_name, rgba) in enumerate(prepared):
        chunks.append(_cel_chunk(idx, 0, 0, rgba.tobytes(), width, height))
    frame = _frame(duration_ms, chunks)
    header = _header(ASE_HEADER_SIZE + len(frame), width, height)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + frame)
    return path
