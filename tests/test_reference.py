"""Unit tests for the Plushy-AI 2.0 Reference Analyzer (Phase 2).

Stdlib unittest only; fixtures are tiny images generated in-memory
with Pillow. Run: python3 -m unittest tests.test_reference
"""
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from reference import (  # noqa: E402
    CATEGORIES,
    MaskCanvas,
    ReferenceError,
    analyze_reference,
    build_mask_record,
    detect_format,
    generation_target,
    ingest_reference,
    load_mask,
    save_mask,
    suggest_mask,
    validate_category,
    validate_upload,
)


def png_bytes(size=(16, 12), color=(200, 30, 30, 255), mode="RGBA"):
    img = Image.new(mode, size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def jpeg_bytes(size=(16, 12)):
    img = Image.new("RGB", size, (30, 200, 30))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def webp_bytes(size=(16, 12)):
    img = Image.new("RGB", size, (30, 30, 200))
    buf = io.BytesIO()
    img.save(buf, format="WEBP")
    return buf.getvalue()


def partially_transparent_png(size=(20, 10)):
    """RGBA image whose opaque content occupies x 5..14, y 2..7."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    for x in range(5, 15):
        for y in range(2, 8):
            img.putpixel((x, y), (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class UploadValidationTests(unittest.TestCase):
    def test_good_png_jpeg_webp_pass(self):
        self.assertEqual(validate_upload("a.png", png_bytes())["format"], "PNG")
        self.assertEqual(validate_upload("a.jpg", jpeg_bytes())["format"], "JPEG")
        self.assertEqual(validate_upload("a.jpeg", jpeg_bytes())["format"], "JPEG")
        self.assertEqual(validate_upload("a.webp", webp_bytes())["format"], "WEBP")

    def test_detect_format_magic_bytes(self):
        self.assertEqual(detect_format(png_bytes()), "PNG")
        self.assertEqual(detect_format(jpeg_bytes()), "JPEG")
        self.assertEqual(detect_format(webp_bytes()), "WEBP")
        self.assertIsNone(detect_format(b"not an image at all"))

    def test_extension_content_mismatch_rejected(self):
        with self.assertRaises(ReferenceError):
            validate_upload("fake.png", jpeg_bytes())
        with self.assertRaises(ReferenceError):
            validate_upload("fake.jpg", png_bytes())
        with self.assertRaises(ReferenceError):
            validate_upload("fake.webp", png_bytes())

    def test_bad_extension_and_garbage_rejected(self):
        with self.assertRaises(ReferenceError):
            validate_upload("a.gif", png_bytes())
        with self.assertRaises(ReferenceError):
            validate_upload("a.png", b"definitely not a png........")
        with self.assertRaises(ReferenceError):
            validate_upload("noext", png_bytes())
        with self.assertRaises(ReferenceError):
            validate_upload("a.png", b"")

    def test_oversize_rejected(self):
        data = png_bytes()
        with self.assertRaises(ReferenceError):
            validate_upload("a.png", data, max_bytes=len(data) - 1)
        # Exactly at the limit passes.
        validate_upload("a.png", data, max_bytes=len(data))


class CategoryTests(unittest.TestCase):
    def test_exact_category_set(self):
        self.assertEqual(
            CATEGORIES,
            ("Hair", "Face", "Top", "Bottom", "One-piece",
             "Shoes", "Armor", "Weapon", "Accessory", "Effects"))
        for cat in CATEGORIES:
            self.assertEqual(validate_category(cat), cat)

    def test_unknown_category_rejected(self):
        for bad in ("hair", "Hat", "", "Background", None):
            with self.assertRaises(ReferenceError):
                validate_category(bad)


class IngestTests(unittest.TestCase):
    def test_traversal_filename_never_used_in_paths(self):
        with tempfile.TemporaryDirectory() as td:
            record = ingest_reference(png_bytes(), "../../evil.png", td)
            stored = Path(td) / record["source"]["stored_filename"]
            self.assertTrue(stored.exists())
            self.assertEqual(stored.resolve().parent, Path(td).resolve())
            self.assertTrue(record["source"]["stored_filename"]
                            .startswith("ref_"))
            self.assertNotIn("evil", record["source"]["stored_filename"])
            self.assertNotIn("..", record["source"]["stored_filename"])
            # Nothing was written outside the storage directory.
            self.assertFalse((Path(td).parent / "evil.png").exists())

    def test_reference_analysis_linkage(self):
        data = png_bytes()
        with tempfile.TemporaryDirectory() as td:
            record = ingest_reference(data, "hero.png", td, category="Top")
            self.assertEqual(record["category"], "Top")
            self.assertEqual(record["source"]["original_filename"], "hero.png")
            sha = hashlib.sha256(data).hexdigest()
            self.assertEqual(record["source"]["sha256"], sha)
            self.assertEqual(record["analysis_sha256"], sha)
            self.assertEqual(record["asset_standard"]["source"]["sha256"], sha)
            self.assertTrue(record["analysis_asset_id"])
            self.assertEqual(record["asset_standard"]["canvas"]["width"], 16)
            # The record JSON on disk matches the returned record.
            on_disk = json.loads(
                (Path(td) / f"{record['reference_id']}.reference.json")
                .read_text(encoding="utf-8"))
            self.assertEqual(on_disk["reference_id"], record["reference_id"])
            # No mask yet -> no generation target.
            self.assertIsNone(record["mask"])
            self.assertIsNone(record["generation_target"])

    def test_ingest_rejects_bad_category_and_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ReferenceError):
                ingest_reference(png_bytes(), "a.png", td, category="Hat")
            with self.assertRaises(ReferenceError):
                ingest_reference(jpeg_bytes(), "a.png", td)

    def test_original_file_not_modified(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "orig.png"
            src.write_bytes(png_bytes())
            before = src.read_bytes()
            record = analyze_reference(src, category="Hair")
            self.assertEqual(src.read_bytes(), before)
            self.assertEqual(record["source"]["original_filename"], "orig.png")


class MaskTests(unittest.TestCase):
    def _record(self, td, data=None, category="Hair"):
        return ingest_reference(data or partially_transparent_png(),
                                "ref.png", td, category=category)

    def test_mask_size_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            record = self._record(td)
            wrong = MaskCanvas(4, 4)
            with self.assertRaises(ReferenceError):
                build_mask_record(record, wrong)
            with self.assertRaises(ReferenceError):
                wrong.validate_size(20, 10)

    def test_add_remove_round_trip(self):
        mask = MaskCanvas(20, 10)
        self.assertTrue(mask.is_empty())
        mask.add_rectangle(2, 2, 6, 4)
        self.assertFalse(mask.is_empty())
        self.assertEqual(mask.bounds(),
                         {"x": 2, "y": 2, "width": 6, "height": 4})
        self.assertEqual(mask.pixel_count(), 24)
        mask.remove_rectangle(2, 2, 3, 4)
        self.assertEqual(mask.pixel_count(), 12)
        self.assertEqual(mask.bounds(),
                         {"x": 5, "y": 2, "width": 3, "height": 4})
        mask.clear()
        self.assertTrue(mask.is_empty())

    def test_rectangle_out_of_bounds_rejected(self):
        mask = MaskCanvas(10, 10)
        for rect in ((-1, 0, 2, 2), (0, 0, 11, 2), (0, 9, 2, 2),
                     (0, 0, 0, 2)):
            with self.assertRaises(ReferenceError):
                mask.add_rectangle(*rect)

    def test_save_as_transparent_png_and_load_back(self):
        with tempfile.TemporaryDirectory() as td:
            record = self._record(td)
            mask = MaskCanvas(20, 10)
            mask.add_rectangle(5, 2, 10, 6)
            path = Path(td) / "m.png"
            rec = save_mask(mask, path, record, confirmed=True)
            with Image.open(path) as img:
                self.assertEqual(img.format, "PNG")
                rgba = img.convert("RGBA")
            # Convention: mask area opaque white, elsewhere transparent.
            self.assertEqual(rgba.getpixel((5, 2)), (255, 255, 255, 255))
            self.assertEqual(rgba.getpixel((0, 0)), (0, 0, 0, 0))
            loaded = load_mask(path, expected_size=(20, 10))
            self.assertEqual(loaded.bounds(), mask.bounds())
            self.assertEqual(loaded.pixel_count(), mask.pixel_count())
            meta = json.loads(Path(td, "m.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["mask_sha256"], rec["mask_sha256"])
            self.assertEqual(meta["reference_id"], record["reference_id"])
            self.assertEqual(meta["category"], "Hair")

    def test_no_confirmed_mask_means_no_generation_target(self):
        with tempfile.TemporaryDirectory() as td:
            record = self._record(td)
            mask = MaskCanvas(20, 10)
            mask.add_rectangle(5, 2, 10, 6)
            unconfirmed = build_mask_record(record, mask, confirmed=False)
            self.assertIsNone(unconfirmed["generation_target"])
            self.assertIsNone(generation_target(unconfirmed))
            self.assertIsNone(generation_target(None))
            confirmed = build_mask_record(record, mask, confirmed=True)
            target = generation_target(confirmed)
            self.assertIsNotNone(target)
            self.assertEqual(target["reference_id"], record["reference_id"])
            self.assertEqual(target["category"], "Hair")
            self.assertEqual(target["bounds"],
                             {"x": 5, "y": 2, "width": 10, "height": 6})
            # A confirmed but EMPTY mask still has no target.
            empty = build_mask_record(record, MaskCanvas(20, 10),
                                      confirmed=True)
            self.assertIsNone(empty["generation_target"])

    def test_suggestion_from_content_bounds_is_unconfirmed(self):
        with tempfile.TemporaryDirectory() as td:
            record = self._record(td)
            mask = suggest_mask(record)
            # Opaque content of the fixture occupies x 5..14, y 2..7.
            self.assertEqual(mask.bounds(),
                             {"x": 5, "y": 2, "width": 10, "height": 6})
            rec = build_mask_record(record, mask)  # default: unconfirmed
            self.assertFalse(rec["confirmed"])
            self.assertIsNone(rec["generation_target"])


if __name__ == "__main__":
    unittest.main()
