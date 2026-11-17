"""Unit tests for the Phase 1 Asset Standard Engine.

Run from the repo root (stdlib only, no test-runner dependency):
    python -m unittest discover -s tests -v

The repository ships no real .aseprite sample, so the Aseprite fixture is
synthesized here byte-by-byte from the published Aseprite file format.
It is a format fixture only - it is NOT an Espil asset and defines no
Espil standard.
"""
import hashlib
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from asset_standard import AssetAnalysisError, analyze_file  # noqa: E402
from asset_standard.analyze import SCHEMA_VERSION  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic Aseprite fixture (built to the published file-format spec)
# ---------------------------------------------------------------------------

def _string(s: str) -> bytes:
    raw = s.encode("utf-8")
    return struct.pack("<H", len(raw)) + raw


def _chunk(chunk_type: int, payload: bytes) -> bytes:
    return struct.pack("<IH", 6 + len(payload), chunk_type) + payload


def _layer_chunk(name: str, flags: int = 1, layer_type: int = 0,
                 child_level: int = 0) -> bytes:
    # layout: flags, type, child level, default w, default h, blend mode
    # (6 words), opacity byte, 3 reserved bytes, name string
    payload = struct.pack("<HHHHH", flags, layer_type, child_level, 0, 0)
    payload += struct.pack("<H", 0)          # blend mode
    payload += struct.pack("<B", 255)        # opacity
    payload += b"\x00" * 3                   # reserved
    payload += _string(name)
    return _chunk(0x2004, payload)


def _palette_chunk() -> bytes:
    payload = struct.pack("<III", 2, 0, 1) + b"\x00" * 8
    payload += struct.pack("<HBBBB", 0, 255, 0, 0, 255)    # red, opaque
    payload += struct.pack("<HBBBB", 0, 0, 0, 255, 128)    # blue, half alpha
    return _chunk(0x2019, payload)


def _cel_chunk(layer_index: int, x: int, y: int, w: int, h: int) -> bytes:
    pixels = zlib.compress(bytes(w * h * 4))
    payload = struct.pack("<Hhh", layer_index, x, y)
    payload += struct.pack("<B", 255)        # opacity
    payload += struct.pack("<H", 2)          # type: compressed image
    payload += struct.pack("<h", 0)          # z-index
    payload += b"\x00" * 5                   # reserved
    payload += struct.pack("<HH", w, h)
    payload += pixels
    return _chunk(0x2005, payload)


def _linked_cel_chunk(layer_index: int, frame_pos: int) -> bytes:
    payload = struct.pack("<Hhh", layer_index, 0, 0)
    payload += struct.pack("<B", 255)
    payload += struct.pack("<H", 1)          # type: linked
    payload += struct.pack("<h", 0)
    payload += b"\x00" * 5
    payload += struct.pack("<H", frame_pos)
    return _chunk(0x2005, payload)


def _tags_chunk() -> bytes:
    return _chunk(0x2018, b"\x00" * 10)  # known type, not extracted in v1


def _frame(duration_ms: int, chunks: list) -> bytes:
    body = b"".join(chunks)
    header = struct.pack("<IHHH", 16 + len(body), 0xF1FA, len(chunks),
                         duration_ms) + b"\x00" * 2 + struct.pack("<I", 0)
    return header + body


def build_fixture() -> bytes:
    frame0 = _frame(100, [_palette_chunk(), _layer_chunk("Body"),
                          _layer_chunk("Hair"), _cel_chunk(0, 2, 3, 4, 5),
                          _tags_chunk()])
    frame1 = _frame(200, [_linked_cel_chunk(1, 0)])
    frames = frame0 + frame1
    header = struct.pack("<IHHHHH", 128 + len(frames), 0xA5E0, 2, 16, 16, 32)
    header += struct.pack("<I", 1)           # flags: layer opacity valid
    header += struct.pack("<H", 0)           # speed (deprecated)
    header += struct.pack("<I", 0) + struct.pack("<I", 0)
    header += struct.pack("<B", 0) + b"\x00" * 3
    header += struct.pack("<H", 0)           # number of colors
    header += struct.pack("<BB", 1, 1)       # pixel w/h
    header += struct.pack("<hhHH", 0, 0, 0, 0)  # grid
    header += b"\x00" * (128 - len(header))
    assert len(header) == 128
    return header + frames


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class PngAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_rgba_content_bounds_and_alpha(self):
        from PIL import Image
        img = Image.new("RGBA", (10, 8), (0, 0, 0, 0))
        for x in range(2, 6):
            for y in range(1, 4):
                img.putpixel((x, y), (255, 0, 0, 255))
        p = self.dir / "sprite.png"
        img.save(p)
        std = analyze_file(p)
        self.assertEqual(std["canvas"]["width"], 10)
        self.assertEqual(std["canvas"]["height"], 8)
        self.assertEqual(std["canvas"]["color_mode"], "RGBA")
        self.assertTrue(std["canvas"]["has_alpha"])
        self.assertEqual(std["content_bounds"],
                         {"x": 2, "y": 1, "width": 4, "height": 3})

    def test_opaque_rgb_bounds_are_full_canvas(self):
        from PIL import Image
        p = self.dir / "flat.png"
        Image.new("RGB", (5, 5), (10, 20, 30)).save(p)
        std = analyze_file(p)
        self.assertFalse(std["canvas"]["has_alpha"])
        self.assertEqual(std["content_bounds"],
                         {"x": 0, "y": 0, "width": 5, "height": 5})

    def test_fully_transparent_warns_and_null_bounds(self):
        from PIL import Image
        p = self.dir / "empty.png"
        Image.new("RGBA", (4, 4), (0, 0, 0, 0)).save(p)
        std = analyze_file(p)
        self.assertIsNone(std["content_bounds"])
        self.assertTrue(any("fully transparent" in w
                            for w in std["validation"]["warnings"]))


class AsepriteAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "fixture_char.aseprite"
        self.path.write_bytes(build_fixture())

    def tearDown(self):
        self.tmp.cleanup()

    def test_metadata_extraction(self):
        std = analyze_file(self.path)
        self.assertEqual(std["source"]["format"], "aseprite")
        self.assertEqual(std["canvas"]["width"], 16)
        self.assertEqual(std["canvas"]["height"], 16)
        self.assertEqual(std["canvas"]["color_mode"], "RGBA")
        self.assertEqual(len(std["frames"]), 2)
        self.assertEqual(std["frames"][0]["duration_ms"], 100)
        self.assertEqual(std["frames"][1]["duration_ms"], 200)
        self.assertEqual(std["palette"], ["#FF0000FF", "#0000FF80"])

    def test_layer_names_order_visibility(self):
        std = analyze_file(self.path)
        names = [layer["name"] for layer in std["layers"]]
        self.assertEqual(names, ["Body", "Hair"])  # file order preserved
        self.assertTrue(all(layer["visible"] for layer in std["layers"]))
        self.assertEqual([layer["index"] for layer in std["layers"]], [0, 1])

    def test_cel_geometry(self):
        std = analyze_file(self.path)
        cel = std["frames"][0]["cels"][0]
        self.assertEqual(cel["layer_index"], 0)
        self.assertEqual((cel["x"], cel["y"]), (2, 3))
        self.assertEqual((cel["width"], cel["height"]), (4, 5))
        self.assertEqual(cel["type"], "compressed")
        linked = std["frames"][1]["cels"][0]
        self.assertEqual(linked["type"], "linked")
        self.assertEqual(linked["linked_frame"], 0)

    def test_unextracted_chunk_is_a_warning_not_silence(self):
        std = analyze_file(self.path)
        self.assertTrue(any("0x2018" in w
                            for w in std["validation"]["warnings"]))
        self.assertEqual(std["validation"]["status"], "needs_review")

    def test_unknown_fields_stay_null(self):
        std = analyze_file(self.path)
        self.assertEqual(std["anchors"], {})
        self.assertEqual(std["directions"], [])
        self.assertIsNone(std["style_profile"]["pixel_scale"])
        self.assertIsNone(std["content_bounds"])  # v1 does not decode cels

    def test_original_file_not_modified(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        analyze_file(self.path)
        after = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.assertEqual(before, after)


class CorruptAsepriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_bad_magic_raises(self):
        p = self.dir / "bad.aseprite"
        data = bytearray(build_fixture())
        data[4:6] = b"\x00\x00"
        p.write_bytes(bytes(data))
        with self.assertRaises(AssetAnalysisError):
            analyze_file(p)

    def test_truncated_file_raises(self):
        p = self.dir / "cut.aseprite"
        p.write_bytes(build_fixture()[:100])  # shorter than the 128B header
        with self.assertRaises(AssetAnalysisError):
            analyze_file(p)

    def test_truncated_frame_raises(self):
        p = self.dir / "cut2.aseprite"
        p.write_bytes(build_fixture()[:140])  # header ok, frame cut off
        with self.assertRaises(AssetAnalysisError):
            analyze_file(p)

    def test_missing_file_raises(self):
        with self.assertRaises(AssetAnalysisError):
            analyze_file(self.dir / "nope.aseprite")


class SchemaTests(unittest.TestCase):
    def test_standard_json_shape(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "fixture_char.aseprite"
            p.write_bytes(build_fixture())
            std = analyze_file(p)
        for key in ("schema_version", "asset_id", "source", "canvas",
                    "frames", "layers", "palette", "content_bounds",
                    "anchors", "directions", "style_profile", "validation"):
            self.assertIn(key, std)
        self.assertEqual(std["schema_version"], SCHEMA_VERSION)
        self.assertEqual(std["asset_id"], "fixture_char")
        json.dumps(std)  # must be JSON-serializable as-is


if __name__ == "__main__":
    unittest.main()
