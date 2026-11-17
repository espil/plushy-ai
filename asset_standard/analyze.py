"""Asset analysis: PNG (via Pillow) and Aseprite (pure-stdlib parser).

The Aseprite parser implements the published Aseprite file format
(https://www.aseprite.org/docs/files/): 128-byte header, per-frame headers,
and typed chunks. It extracts metadata only - cel pixel data is never
decompressed in v1, so `content_bounds` stays null for Aseprite files.

Rules (Plushy-AI 2.0 development prompt, Phase 1):
  - Original files are opened read-only and never modified.
  - Chunk types the parser does not extract are reported as warnings,
    never silently skipped.
  - Structural corruption (bad magic, truncated data, out-of-range chunk
    sizes) raises AssetAnalysisError instead of producing a partial record.
  - Values that cannot be measured (anchors, directions, style profile)
    are emitted as null/empty, never estimated.
"""

from __future__ import annotations

import hashlib
import re
import struct
from pathlib import Path

SCHEMA_VERSION = "1.0"

ASE_HEADER_SIZE = 128
ASE_HEADER_MAGIC = 0xA5E0
ASE_FRAME_MAGIC = 0xF1FA

# Chunk types (Aseprite file format spec).
CHUNK_OLD_PALETTE_A = 0x0004
CHUNK_OLD_PALETTE_B = 0x0011
CHUNK_LAYER = 0x2004
CHUNK_CEL = 0x2005
CHUNK_CEL_EXTRA = 0x2006
CHUNK_COLOR_PROFILE = 0x2007
CHUNK_EXTERNAL_FILES = 0x2008
CHUNK_MASK = 0x2016
CHUNK_PATH = 0x2017
CHUNK_TAGS = 0x2018
CHUNK_PALETTE = 0x2019
CHUNK_USER_DATA = 0x2020
CHUNK_SLICE = 0x2022
CHUNK_TILESET = 0x2023

KNOWN_UNEXTRACTED = {
    CHUNK_CEL_EXTRA: "cel extra",
    CHUNK_COLOR_PROFILE: "color profile",
    CHUNK_EXTERNAL_FILES: "external files",
    CHUNK_MASK: "mask (deprecated)",
    CHUNK_PATH: "path",
    CHUNK_TAGS: "tags",
    CHUNK_USER_DATA: "user data",
    CHUNK_SLICE: "slice",
    CHUNK_TILESET: "tileset",
}

LAYER_TYPES = {0: "image", 1: "group", 2: "tilemap"}
CEL_TYPES = {0: "raw", 1: "linked", 2: "compressed", 3: "compressed_tilemap"}
DEPTH_MODES = {32: "RGBA", 16: "Grayscale", 8: "Indexed"}


class AssetAnalysisError(Exception):
    """Raised when a file cannot be analyzed (corrupt or unsupported)."""


def _asset_id(path: Path) -> str:
    stem = re.sub(r"[^a-z0-9_-]+", "_", path.stem.lower()).strip("_")
    return stem or "asset"


def _blank_standard(path: Path, fmt: str, data: bytes) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "asset_id": _asset_id(path),
        "source": {
            "filename": path.name,
            "format": fmt,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        "canvas": {"width": None, "height": None, "color_mode": None,
                   "has_alpha": None},
        "frames": [],
        "layers": [],
        "palette": [],
        "content_bounds": None,
        "anchors": {},
        "directions": [],
        "style_profile": {"pixel_scale": None, "outline": None,
                          "antialiasing": None},
        "validation": {"status": "needs_review", "warnings": []},
    }


def _finish(std: dict) -> dict:
    if not std["validation"]["warnings"]:
        std["validation"]["status"] = "ok"
    return std


# ---------------------------------------------------------------------------
# PNG / general raster analysis (Pillow)
# ---------------------------------------------------------------------------

def _analyze_raster(path: Path, data: bytes) -> dict:
    from PIL import Image

    std = _blank_standard(path, path.suffix.lower().lstrip(".") or "raster",
                          data)
    warnings = std["validation"]["warnings"]
    try:
        img = Image.open(path)
        img.load()
    except Exception as e:  # noqa: BLE001 - surfaced as analysis error
        raise AssetAnalysisError(f"cannot read image: {e}") from e

    std["source"]["format"] = (img.format or std["source"]["format"]).lower()
    has_alpha = (
        img.mode in ("RGBA", "LA", "PA")
        or (img.mode == "P" and "transparency" in img.info)
    )
    std["canvas"] = {
        "width": img.width,
        "height": img.height,
        "color_mode": img.mode,
        "has_alpha": has_alpha,
    }

    if img.mode == "P":
        raw = img.getpalette() or []
        std["palette"] = [
            "#{:02X}{:02X}{:02X}FF".format(raw[i], raw[i + 1], raw[i + 2])
            for i in range(0, len(raw) - 2, 3)
        ]

    if has_alpha:
        alpha = img.convert("RGBA").getchannel("A")
        bbox = alpha.getbbox()
        if bbox is None:
            warnings.append("image is fully transparent; "
                            "content_bounds is null")
        else:
            std["content_bounds"] = {
                "x": bbox[0], "y": bbox[1],
                "width": bbox[2] - bbox[0], "height": bbox[3] - bbox[1],
            }
    else:
        std["content_bounds"] = {"x": 0, "y": 0,
                                 "width": img.width, "height": img.height}

    n_frames = getattr(img, "n_frames", 1)
    std["frames"] = [
        {"index": i, "duration_ms": None, "cels": []}
        for i in range(n_frames)
    ]
    if n_frames == 1:
        std["layers"] = [{"index": 0, "name": "(single layer)",
                          "type": "image", "visible": True,
                          "child_level": 0, "blend_mode": None,
                          "opacity": None}]
    return _finish(std)


# ---------------------------------------------------------------------------
# Aseprite analysis (pure stdlib, format spec linked in module docstring)
# ---------------------------------------------------------------------------

class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def take(self, n: int, what: str) -> bytes:
        if n < 0 or self.pos + n > len(self.data):
            raise AssetAnalysisError(
                f"truncated file: need {n} bytes for {what} at offset "
                f"{self.pos}, file is {len(self.data)} bytes")
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def u8(self, what: str = "byte") -> int:
        return self.take(1, what)[0]

    def u16(self, what: str = "word") -> int:
        return struct.unpack("<H", self.take(2, what))[0]

    def i16(self, what: str = "short") -> int:
        return struct.unpack("<h", self.take(2, what))[0]

    def u32(self, what: str = "dword") -> int:
        return struct.unpack("<I", self.take(4, what))[0]

    def string(self, what: str = "string") -> str:
        n = self.u16(what + " length")
        raw = self.take(n, what)
        return raw.decode("utf-8", errors="replace")


def _parse_palette_chunk(r: _Reader, end: int, palette: dict) -> None:
    _total = r.u32("palette size")
    first = r.u32("palette first index")
    last = r.u32("palette last index")
    r.take(8, "palette reserved")
    for idx in range(first, last + 1):
        if r.pos >= end:
            raise AssetAnalysisError("palette chunk ends mid-entry")
        flags = r.u16("palette entry flags")
        red, green, blue, alpha = (r.u8("palette R"), r.u8("palette G"),
                                   r.u8("palette B"), r.u8("palette A"))
        if flags & 1:
            r.string("palette color name")
        palette[idx] = "#{:02X}{:02X}{:02X}{:02X}".format(red, green, blue,
                                                          alpha)


def _parse_old_palette(r: _Reader, end: int, palette: dict,
                       six_bit: bool) -> None:
    packets = r.u16("old palette packet count")
    idx = 0
    for _ in range(packets):
        idx += r.u8("old palette skip")
        count = r.u8("old palette color count") or 256
        for _ in range(count):
            if r.pos >= end:
                raise AssetAnalysisError("old palette chunk ends mid-entry")
            red, green, blue = r.u8("old palette R"), r.u8("old palette G"), \
                r.u8("old palette B")
            if six_bit:  # 0x0004 stores 0-63 components
                red, green, blue = (v * 255 // 63 for v in (red, green, blue))
            palette[idx] = "#{:02X}{:02X}{:02X}FF".format(red, green, blue)
            idx += 1


def _parse_layer_chunk(r: _Reader, opacity_valid: bool) -> dict:
    flags = r.u16("layer flags")
    layer_type = r.u16("layer type")
    child_level = r.u16("layer child level")
    r.u16("layer default width")   # ignored per spec
    r.u16("layer default height")  # ignored per spec
    blend_mode = r.u16("layer blend mode")
    opacity = r.u8("layer opacity")
    r.take(3, "layer reserved")
    name = r.string("layer name")
    layer = {
        "name": name,
        "type": LAYER_TYPES.get(layer_type, f"unknown({layer_type})"),
        "visible": bool(flags & 1),
        "child_level": child_level,
        "blend_mode": blend_mode,
        "opacity": opacity if opacity_valid else None,
    }
    if layer_type == 2:
        layer["tileset_index"] = r.u32("layer tileset index")
    return layer


def _parse_cel_chunk(r: _Reader) -> dict:
    # Spec order: layer index, x, y, opacity, cel type, z-index,
    # 5 reserved bytes, then the type-specific payload.
    layer_index = r.u16("cel layer index")
    x = r.i16("cel x")
    y = r.i16("cel y")
    opacity = r.u8("cel opacity")
    cel_type = r.u16("cel type")
    z_index = r.i16("cel z-index")
    r.take(5, "cel reserved")
    cel = {
        "layer_index": layer_index,
        "x": x,
        "y": y,
        "opacity": opacity,
        "type": None,
        "z_index": z_index,
        "width": None,
        "height": None,
        "linked_frame": None,
    }
    cel["type"] = CEL_TYPES.get(cel_type, f"unknown({cel_type})")
    if cel_type in (0, 2, 3):
        cel["width"] = r.u16("cel width")
        cel["height"] = r.u16("cel height")
        # Pixel data follows (raw or zlib); v1 records geometry only.
    elif cel_type == 1:
        cel["linked_frame"] = r.u16("cel linked frame")
    return cel


def _analyze_aseprite(path: Path, data: bytes) -> dict:
    if len(data) < ASE_HEADER_SIZE:
        raise AssetAnalysisError(
            f"file too small for an Aseprite header ({len(data)} bytes)")
    r = _Reader(data)
    _file_size = r.u32("header file size")
    magic = r.u16("header magic")
    if magic != ASE_HEADER_MAGIC:
        raise AssetAnalysisError(
            f"bad Aseprite magic 0x{magic:04X} (expected 0xA5E0)")
    frame_count = r.u16("header frame count")
    width = r.u16("header width")
    height = r.u16("header height")
    depth = r.u16("header color depth")
    flags = r.u32("header flags")
    r.pos = ASE_HEADER_SIZE  # skip the rest of the fixed header

    std = _blank_standard(path, "aseprite", data)
    warnings = std["validation"]["warnings"]
    std["canvas"] = {
        "width": width,
        "height": height,
        "color_mode": DEPTH_MODES.get(depth, f"depth{depth}"),
        "has_alpha": True,  # every Aseprite color mode carries an alpha byte
    }
    if depth not in DEPTH_MODES:
        warnings.append(f"unusual color depth {depth}")

    palette: dict[int, str] = {}
    layers: list[dict] = []

    for fi in range(frame_count):
        if r.pos + 16 > len(data):
            raise AssetAnalysisError(f"truncated file: frame {fi} header "
                                     f"missing at offset {r.pos}")
        frame_start = r.pos
        frame_bytes = r.u32("frame size")
        frame_magic = r.u16("frame magic")
        if frame_magic != ASE_FRAME_MAGIC:
            raise AssetAnalysisError(
                f"bad frame magic 0x{frame_magic:04X} at frame {fi}")
        old_chunks = r.u16("frame chunk count (old)")
        duration = r.u16("frame duration")
        r.take(2, "frame reserved")
        new_chunks = r.u32("frame chunk count (new)")
        chunk_count = new_chunks if old_chunks == 0xFFFF else old_chunks
        frame_end = frame_start + frame_bytes
        if frame_bytes < 16 or frame_end > len(data):
            raise AssetAnalysisError(
                f"frame {fi} size {frame_bytes} out of range "
                f"(file is {len(data)} bytes)")

        frame = {"index": fi, "duration_ms": duration, "cels": []}
        for _ in range(chunk_count):
            if r.pos + 6 > frame_end:
                raise AssetAnalysisError(
                    f"truncated chunk header in frame {fi}")
            chunk_start = r.pos
            chunk_size = r.u32("chunk size")
            chunk_type = r.u16("chunk type")
            if chunk_size < 6 or chunk_start + chunk_size > frame_end:
                raise AssetAnalysisError(
                    f"chunk size {chunk_size} out of range in frame {fi} "
                    f"at offset {chunk_start}")
            chunk_end = chunk_start + chunk_size
            if chunk_type == CHUNK_LAYER:
                layer = _parse_layer_chunk(r, opacity_valid=bool(flags & 1))
                layer["index"] = len(layers)
                layers.append(layer)
            elif chunk_type == CHUNK_CEL:
                frame["cels"].append(_parse_cel_chunk(r))
            elif chunk_type == CHUNK_PALETTE:
                _parse_palette_chunk(r, chunk_end, palette)
            elif chunk_type in (CHUNK_OLD_PALETTE_A, CHUNK_OLD_PALETTE_B):
                _parse_old_palette(r, chunk_end, palette,
                                   six_bit=(chunk_type == CHUNK_OLD_PALETTE_A))
            elif chunk_type in KNOWN_UNEXTRACTED:
                warnings.append(
                    f"frame {fi}: chunk 0x{chunk_type:04X} "
                    f"({KNOWN_UNEXTRACTED[chunk_type]}) present but not "
                    f"extracted by analyzer v1")
            else:
                warnings.append(
                    f"frame {fi}: unknown chunk type 0x{chunk_type:04X} "
                    f"skipped ({chunk_size} bytes)")
            if r.pos > chunk_end:
                raise AssetAnalysisError(
                    f"chunk 0x{chunk_type:04X} in frame {fi} over-read "
                    f"({r.pos - chunk_end} bytes past its declared size)")
            r.pos = chunk_end
        std["frames"].append(frame)
        r.pos = frame_end

    std["layers"] = layers
    if palette:
        std["palette"] = [palette[i] for i in sorted(palette)]
    warnings.append("content_bounds is null for Aseprite files: analyzer "
                    "v1 records cel geometry but does not decode cel "
                    "pixel data")
    return _finish(std)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def analyze_file(path) -> dict:
    """Analyze one asset file and return the asset-standard dict.

    Read-only. Raises AssetAnalysisError on corrupt/unsupported input.
    Format is chosen by content first (Aseprite magic), then extension.
    """
    path = Path(path)
    if not path.exists():
        raise AssetAnalysisError(f"file not found: {path}")
    data = path.read_bytes()
    if len(data) >= 6 and struct.unpack_from("<H", data, 4)[0] == \
            ASE_HEADER_MAGIC:
        return _analyze_aseprite(path, data)
    if path.suffix.lower() in (".ase", ".aseprite"):
        return _analyze_aseprite(path, data)  # raises with a precise reason
    return _analyze_raster(path, data)
