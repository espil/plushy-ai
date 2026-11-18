"""Unit tests for the Phase 5 Aseprite Bridge / Export.

Run from the repo root (stdlib only, no test-runner dependency):
    python -m unittest discover -s tests -v

The headline test is the ASE round-trip: a layered .aseprite written
by exporter.aseprite_write must parse back through the Phase 1
analyzer (asset_standard.analyze_file) with layer names/order, canvas,
frame count and cel geometry intact. Fixtures are synthetic images
built with Pillow - they are format fixtures only, not Espil assets.
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

from PIL import Image  # noqa: E402

from asset_standard import analyze_file  # noqa: E402
from exporter import ExportError, export_assets, write_aseprite  # noqa: E402
from exporter.aseprite_write import AsepriteWriteError  # noqa: E402

DIRECTIONS = ("S", "SE", "E", "NE", "N", "NW", "W", "SW")
COLORS = {"S": (255, 0, 0, 255), "SE": (255, 128, 0, 255),
          "E": (255, 255, 0, 255), "NE": (0, 255, 0, 255),
          "N": (0, 255, 255, 255), "NW": (0, 0, 255, 255),
          "W": (128, 0, 255, 255), "SW": (255, 0, 255, 255)}


def _png(path, size=(16, 12), color=(200, 30, 30, 255)):
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    for x in range(2, size[0] - 2):
        for y in range(2, size[1] - 2):
            img.putpixel((x, y), color)
    img.save(path)
    return path


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def direction_set(self, skip=(), size=(16, 12)):
        out = {}
        for d in DIRECTIONS:
            if d in skip:
                continue
            out[d] = _png(self.dir / f"dir_{d}.png", size=size,
                          color=COLORS[d])
        return out


class AsepriteWriteTests(_Tmp):
    def test_header_magic_and_format(self):
        p = write_aseprite(self.dir / "a.aseprite",
                           [("Body", Image.new("RGBA", (8, 8)))])
        data = p.read_bytes()
        self.assertEqual(struct.unpack_from("<I", data, 0)[0], len(data))
        self.assertEqual(struct.unpack_from("<H", data, 4)[0], 0xA5E0)
        self.assertEqual(struct.unpack_from("<H", data, 6)[0], 1)   # frames
        self.assertEqual(struct.unpack_from("<HH", data, 8), (8, 8))
        self.assertEqual(struct.unpack_from("<H", data, 12)[0], 32)  # depth

    def test_roundtrip_through_phase1_analyzer(self):
        layers = [("Body", Image.new("RGBA", (20, 14), (10, 20, 30, 255))),
                  ("Top", Image.new("RGBA", (20, 14), (40, 50, 60, 255))),
                  ("Hair", Image.new("RGBA", (20, 14), (70, 80, 90, 255)))]
        p = write_aseprite(self.dir / "char.aseprite", layers)
        std = analyze_file(p)
        self.assertEqual(std["source"]["format"], "aseprite")
        self.assertEqual(std["canvas"]["width"], 20)
        self.assertEqual(std["canvas"]["height"], 14)
        self.assertEqual(std["canvas"]["color_mode"], "RGBA")
        self.assertEqual([layer["name"] for layer in std["layers"]],
                         ["Body", "Top", "Hair"])
        self.assertTrue(all(layer["visible"] for layer in std["layers"]))
        self.assertEqual(len(std["frames"]), 1)
        cels = std["frames"][0]["cels"]
        self.assertEqual(len(cels), 3)
        for i, cel in enumerate(cels):
            self.assertEqual(cel["layer_index"], i)
            self.assertEqual(cel["type"], "compressed")
            self.assertEqual((cel["x"], cel["y"]), (0, 0))
            self.assertEqual((cel["width"], cel["height"]), (20, 14))

    def test_cel_pixel_data_is_real_zlib_rgba(self):
        img = Image.new("RGBA", (4, 3), (0, 0, 0, 0))
        img.putpixel((1, 1), (255, 0, 0, 255))
        p = write_aseprite(self.dir / "px.aseprite", [("L", img)])
        data = p.read_bytes()
        # Find the cel chunk (0x2005) and decompress its pixel payload:
        # the cel payload header is 20 bytes (layer,x,y,opacity,type,
        # z-index,5 reserved,width,height) after the 6-byte chunk header.
        pos = data.find(struct.pack("<H", 0x2005), 128)
        chunk_size = struct.unpack_from("<I", data, pos - 4)[0]
        payload = data[pos + 2 + 20: pos - 4 + chunk_size]
        raw = zlib.decompress(payload)
        self.assertEqual(len(raw), 4 * 3 * 4)
        self.assertEqual(raw[(1 * 4 + 1) * 4:(1 * 4 + 1) * 4 + 4],
                         bytes((255, 0, 0, 255)))

    def test_size_mismatch_between_layers_refused(self):
        with self.assertRaises(AsepriteWriteError):
            write_aseprite(self.dir / "bad.aseprite",
                           [("A", Image.new("RGBA", (8, 8))),
                            ("B", Image.new("RGBA", (9, 8)))])

    def test_duplicate_layer_name_refused(self):
        with self.assertRaises(AsepriteWriteError):
            write_aseprite(self.dir / "bad.aseprite",
                           [("A", Image.new("RGBA", (8, 8))),
                            ("A", Image.new("RGBA", (8, 8)))])

    def test_no_layers_refused(self):
        with self.assertRaises(AsepriteWriteError):
            write_aseprite(self.dir / "bad.aseprite", [])


class ExportTests(_Tmp):
    def test_full_direction_export_ok(self):
        out = self.dir / "export"
        manifest = export_assets(out, direction_images=self.direction_set(),
                                 asset_id="hero")
        self.assertEqual(manifest["status"], "ok")
        self.assertEqual(manifest["validation"]["directions_ok"], 8)
        sheet = Image.open(out / "sprite_sheet.png")
        self.assertEqual(sheet.size, (64, 24))  # 4x2 grid of 16x12 cells
        self.assertTrue((out / "export_manifest.json").exists())
        self.assertEqual(len(manifest["outputs"]["png_copies"]), 8)

    def test_sheet_cell_placement_pixels(self):
        out = self.dir / "export"
        export_assets(out, direction_images=self.direction_set())
        sheet = Image.open(out / "sprite_sheet.png").convert("RGBA")
        # S is cell (0,0); its content starts at cell origin + (2,2).
        self.assertEqual(sheet.getpixel((2, 2)), COLORS["S"])
        # NE is index 3 -> cell (48,0); content at +(2,2).
        self.assertEqual(sheet.getpixel((50, 2)), COLORS["NE"])
        # SW is index 7 -> cell (48,12); content at +(2,2).
        self.assertEqual(sheet.getpixel((50, 14)), COLORS["SW"])
        # A cell corner outside the drawn content stays transparent.
        self.assertEqual(sheet.getpixel((0, 0)), (0, 0, 0, 0))

    def test_missing_direction_marked_not_dropped(self):
        out = self.dir / "export"
        manifest = export_assets(
            out, direction_images=self.direction_set(skip=("W", "SW")))
        self.assertEqual(manifest["status"], "needs_review")
        self.assertEqual(manifest["validation"]["directions_missing"], 2)
        by_dir = {e["direction"]: e for e in manifest["directions"]}
        self.assertEqual(len(by_dir), 8)
        self.assertEqual(by_dir["W"]["status"], "missing")
        self.assertFalse(by_dir["W"]["packed"])
        # The missing cell stays empty; neighbours keep their cells.
        sheet = Image.open(out / "sprite_sheet.png").convert("RGBA")
        self.assertEqual(sheet.getpixel((2 + 32, 14)), (0, 0, 0, 0))  # W cell

    def test_size_mismatch_direction_flagged_and_not_packed(self):
        dirs = self.direction_set()
        _png(self.dir / "dir_E.png", size=(10, 10), color=COLORS["E"])
        out = self.dir / "export"
        manifest = export_assets(out, direction_images=dirs)
        by_dir = {e["direction"]: e for e in manifest["directions"]}
        self.assertEqual(by_dir["E"]["status"], "needs_review")
        self.assertFalse(by_dir["E"]["packed"])
        self.assertTrue(any("size mismatch" in w
                            for w in by_dir["E"]["warnings"]))
        self.assertEqual(manifest["status"], "needs_review")

    def test_no_alpha_flagged(self):
        p = self.dir / "flat.png"
        Image.new("RGB", (16, 12), (10, 10, 10)).save(p)
        out = self.dir / "export"
        manifest = export_assets(out, direction_images={"S": p})
        by_dir = {e["direction"]: e for e in manifest["directions"]}
        self.assertEqual(by_dir["S"]["status"], "needs_review")
        self.assertTrue(any("no alpha" in w for w in by_dir["S"]["warnings"]))

    def test_png_only_path_without_aseprite(self):
        out = self.dir / "export"
        manifest = export_assets(out, direction_images=self.direction_set())
        self.assertIsNone(manifest["outputs"]["aseprite"])
        self.assertFalse(list(out.glob("*.aseprite")))
        self.assertTrue((out / "sprite_sheet.png").exists())

    def test_layered_aseprite_export_with_roundtrip(self):
        body = _png(self.dir / "body.png", color=(10, 10, 200, 255))
        hair = _png(self.dir / "hair.png", color=(200, 10, 10, 255))
        out = self.dir / "export"
        manifest = export_assets(out, layers=[("Body", body),
                                              ("Hair", hair)],
                                 aseprite_name="char.aseprite")
        ase = manifest["outputs"]["aseprite"]
        self.assertEqual(ase["status"], "ok")
        self.assertEqual(ase["roundtrip"]["status"], "passed")
        self.assertEqual(ase["roundtrip"]["layers"], ["Body", "Hair"])
        self.assertEqual(ase["sha256"], _sha(out / "char.aseprite"))
        self.assertEqual(manifest["status"], "ok")
        # And independently: the Phase 1 analyzer reads the file.
        std = analyze_file(out / "char.aseprite")
        self.assertEqual([layer["name"] for layer in std["layers"]],
                         ["Body", "Hair"])

    def test_aseprite_skipped_when_layer_mismatched(self):
        body = _png(self.dir / "body.png", size=(16, 12))
        hair = _png(self.dir / "hair.png", size=(8, 8))
        out = self.dir / "export"
        manifest = export_assets(out, layers=[("Body", body),
                                              ("Hair", hair)],
                                 aseprite_name="char.aseprite")
        ase = manifest["outputs"]["aseprite"]
        self.assertEqual(ase["status"], "needs_review")
        self.assertFalse((out / "char.aseprite").exists())
        self.assertEqual(manifest["status"], "needs_review")

    def test_source_standard_preserved_in_manifest(self):
        src = _png(self.dir / "src.png")
        std = analyze_file(src)
        std_path = self.dir / "src.asset_standard.json"
        std_path.write_text(json.dumps(std), encoding="utf-8")
        out = self.dir / "export"
        manifest = export_assets(out, layers=[("Top", src)],
                                 source_standard=std_path)
        preserved = manifest["source_standard"]
        self.assertEqual(preserved["sha256"], _sha(std_path))
        self.assertEqual(preserved["record"]["asset_id"], std["asset_id"])
        self.assertEqual(preserved["source_sha256"], std["source"]["sha256"])

    def test_originals_unmodified(self):
        dirs = self.direction_set()
        before = {d: _sha(p) for d, p in dirs.items()}
        export_assets(self.dir / "export", direction_images=dirs,
                      layers=[("Body", dirs["S"])],
                      aseprite_name="x.aseprite")
        self.assertEqual(before, {d: _sha(p) for d, p in dirs.items()})

    def test_empty_export_refused(self):
        with self.assertRaises(ExportError):
            export_assets(self.dir / "export")

    def test_unknown_direction_refused(self):
        p = _png(self.dir / "x.png")
        with self.assertRaises(ExportError):
            export_assets(self.dir / "export", direction_images={"UP": p})


if __name__ == "__main__":
    unittest.main()
