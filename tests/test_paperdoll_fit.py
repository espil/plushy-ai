"""Unit tests for the Plushy-AI 2.0 Paper Doll Integration (Phase 4).

Stdlib unittest only. PLUSHY_MOCK is forced on before any pipeline
import can happen (fitting imports paperdoll lazily, and paperdoll
imports pipeline_sprite), so no GPU, torch or model is involved.

Run: PLUSHY_MOCK=1 python3 -m unittest tests.test_paperdoll_fit
"""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["PLUSHY_MOCK"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from fitting import (  # noqa: E402
    COMPOSE_ORDER,
    DIRECTIONS,
    FittingError,
    discover_bodies,
    extract_layer,
    fit_layers,
)

SIZE = (16, 16)
BODY_COLOR = (200, 180, 160, 255)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def body_file(path, size=SIZE, color=BODY_COLOR):
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    # body occupies a centred block, transparent margin around it
    for x in range(4, 12):
        for y in range(2, 14):
            img.putpixel((x, y), color)
    img.save(path, format="PNG")
    return path


def layer_file(path, size=SIZE, pixels=None):
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    for (x, y), color in (pixels or {}).items():
        img.putpixel((x, y), color)
    img.save(path, format="PNG")
    return path


class FitTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.body_dir = self.root / "bodies"
        self.body_dir.mkdir()
        self.out = self.root / "out"

    def tearDown(self):
        self._tmp.cleanup()

    def make_bodies(self, directions=DIRECTIONS):
        bodies = {}
        for d in directions:
            p = body_file(self.body_dir / f"body_{d}_s0.png")
            bodies[d] = p
        return bodies


class ComposeOrderTests(FitTestBase):
    def test_compose_order_respected_by_pixel_probe(self):
        bodies = self.make_bodies(("S",))
        # all three layers paint the same pixel; the last slot in
        # the canonical order (hair_front) must win
        probe = (6, 6)
        hair_back = layer_file(self.root / "hb.png",
                               pixels={probe: (255, 0, 0, 255)})
        tops = layer_file(self.root / "tp.png",
                          pixels={probe: (0, 255, 0, 255)})
        hair_front = layer_file(self.root / "hf.png",
                                pixels={probe: (0, 0, 255, 255)})
        manifest = fit_layers(
            bodies,
            # input order deliberately NOT the compose order
            [{"slot": "hair_front", "path": str(hair_front)},
             {"slot": "tops", "path": str(tops)},
             {"slot": "hair_back", "path": str(hair_back)}],
            self.out)
        entry = next(e for e in manifest["entries"]
                     if e["direction"] == "S")
        self.assertEqual(entry["status"], "ok")
        composite = Image.open(
            self.out / entry["outputs"]["composite"]["filename"])
        self.assertEqual(composite.getpixel(probe), (0, 0, 255, 255))
        # hair_back is UNDER the body: a pixel only hair_back and
        # the body paint keeps the body colour
        self.assertEqual(composite.getpixel((5, 5)), BODY_COLOR)

    def test_layer_and_composite_outputs_both_exist(self):
        bodies = self.make_bodies(("S",))
        tops = layer_file(self.root / "tp.png",
                          pixels={(6, 6): (0, 255, 0, 255)})
        manifest = fit_layers(bodies,
                              [{"slot": "tops", "path": str(tops)}],
                              self.out)
        entry = next(e for e in manifest["entries"]
                     if e["direction"] == "S")
        layer_out = self.out / entry["outputs"]["layers"]["tops"]["filename"]
        composite = self.out / entry["outputs"]["composite"]["filename"]
        self.assertTrue(layer_out.is_file())
        self.assertTrue(composite.is_file())
        self.assertEqual(entry["outputs"]["layers"]["tops"]["sha256"],
                         sha256(layer_out))
        # the layer copy is the layer alone, not the composite
        layer_img = Image.open(layer_out)
        self.assertEqual(layer_img.getpixel((5, 5)), (0, 0, 0, 0))
        self.assertEqual(layer_img.getpixel((6, 6)), (0, 255, 0, 255))


class ValidationTests(FitTestBase):
    def test_size_mismatch_needs_review_not_resized(self):
        bodies = self.make_bodies(("S",))
        small = layer_file(self.root / "small.png", size=(8, 8),
                           pixels={(1, 1): (0, 255, 0, 255)})
        manifest = fit_layers(bodies,
                              [{"slot": "tops", "path": str(small)}],
                              self.out)
        entry = next(e for e in manifest["entries"]
                     if e["direction"] == "S")
        self.assertEqual(entry["status"], "needs_review")
        self.assertFalse(entry["validation"]["size_match"])
        self.assertEqual(entry["validation"]["body_size"],
                         {"width": 16, "height": 16})
        self.assertEqual(entry["layers"][0]["size"],
                         {"width": 8, "height": 8})
        self.assertIsNone(entry["outputs"])
        # nothing was resized into a composite behind our back
        self.assertFalse((self.out / "worn_S.png").exists())

    def test_missing_directions_explicitly_marked(self):
        bodies = self.make_bodies(("S", "E"))
        tops = layer_file(self.root / "tp.png",
                          pixels={(6, 6): (0, 255, 0, 255)})
        manifest = fit_layers(bodies,
                              [{"slot": "tops", "path": str(tops)}],
                              self.out)
        self.assertEqual(len(manifest["entries"]), 8)
        by_dir = {e["direction"]: e for e in manifest["entries"]}
        self.assertEqual(by_dir["S"]["status"], "ok")
        self.assertEqual(by_dir["E"]["status"], "ok")
        for d in ("SE", "NE", "N", "NW", "W", "SW"):
            self.assertEqual(by_dir[d]["status"], "missing")
            self.assertIn("body", by_dir[d]["missing"])
        self.assertEqual(manifest["summary"]["missing"], 6)

    def test_missing_layer_side_named(self):
        bodies = self.make_bodies(("S",))
        # layer file names direction E only -> S lacks the layer
        tops_e = layer_file(self.root / "layer_E_p0_s0.png",
                            pixels={(6, 6): (0, 255, 0, 255)})
        manifest = fit_layers(bodies,
                              [{"slot": "tops", "path": str(tops_e)}],
                              self.out)
        entry = next(e for e in manifest["entries"]
                     if e["direction"] == "S")
        self.assertEqual(entry["status"], "missing")
        self.assertIn("layer:tops", entry["missing"])
        self.assertNotIn("body", entry["missing"])

    def test_alignment_bounds_recorded(self):
        bodies = self.make_bodies(("S",))
        tops = layer_file(self.root / "tp.png",
                          pixels={(6, 6): (0, 255, 0, 255),
                                  (9, 10): (0, 255, 0, 255)})
        manifest = fit_layers(bodies,
                              [{"slot": "tops", "path": str(tops)}],
                              self.out)
        entry = next(e for e in manifest["entries"]
                     if e["direction"] == "S")
        alignment = entry["validation"]["alignment"]
        self.assertEqual(alignment["body_content_bounds"],
                         {"x": 4, "y": 2, "width": 8, "height": 12})
        self.assertEqual(alignment["layers"]["tops"],
                         {"x": 6, "y": 6, "width": 4, "height": 5})


class ManifestTests(FitTestBase):
    def test_manifest_order_names_and_hashes(self):
        bodies = self.make_bodies(("S",))
        tops = layer_file(self.root / "tp.png",
                          pixels={(6, 6): (0, 255, 0, 255)})
        hair_back = layer_file(self.root / "hb.png",
                               pixels={(6, 6): (255, 0, 0, 255)})
        manifest = fit_layers(
            bodies,
            [{"slot": "tops", "path": str(tops), "name": "red-hoodie"},
             {"slot": "hair_back", "path": str(hair_back),
              "name": "long-hair-back"}],
            self.out)
        self.assertEqual(manifest["compose_order"],
                         ["hair_back", "body", "bottoms", "tops",
                          "shoes", "face", "hair_front"])
        self.assertEqual(manifest["directions_order"], list(DIRECTIONS))
        entry = next(e for e in manifest["entries"]
                     if e["direction"] == "S")
        slots = [layer["slot"] for layer in entry["layers"]]
        self.assertEqual(slots, ["hair_back", "tops"])  # compose order
        names = {layer["slot"]: layer["name"]
                 for layer in entry["layers"]}
        self.assertEqual(names["tops"], "red-hoodie")
        self.assertEqual(entry["body"]["sha256"],
                         sha256(bodies["S"]))
        on_disk = json.loads(
            (self.out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["schema_version"],
                         manifest["schema_version"])

    def test_anchors_stay_null(self):
        bodies = self.make_bodies(("S",))
        tops = layer_file(self.root / "tp.png",
                          pixels={(6, 6): (0, 255, 0, 255)})
        manifest = fit_layers(bodies,
                              [{"slot": "tops", "path": str(tops)}],
                              self.out)
        self.assertIsNone(manifest["anchors"])
        self.assertIn("anchors_note", manifest)
        for entry in manifest["entries"]:
            self.assertIsNone(entry["anchors"])

    def test_originals_unmodified(self):
        bodies = self.make_bodies(("S", "E"))
        tops = layer_file(self.root / "tp.png",
                          pixels={(6, 6): (0, 255, 0, 255)})
        before = {p: sha256(p) for p in list(bodies.values()) + [tops]}
        fit_layers(bodies, [{"slot": "tops", "path": str(tops)}],
                   self.out)
        after = {p: sha256(p) for p in list(bodies.values()) + [tops]}
        self.assertEqual(before, after)

    def test_plain_layer_records_generation_null(self):
        bodies = self.make_bodies(("S",))
        tops = layer_file(self.root / "tp.png",
                          pixels={(6, 6): (0, 255, 0, 255)})
        manifest = fit_layers(bodies,
                              [{"slot": "tops", "path": str(tops)}],
                              self.out)
        self.assertIsNone(manifest["generation"])

    def test_unknown_slot_rejected(self):
        bodies = self.make_bodies(("S",))
        tops = layer_file(self.root / "tp.png")
        with self.assertRaises(FittingError):
            fit_layers(bodies,
                       [{"slot": "weapon", "path": str(tops)}],
                       self.out)


class GenerationLinkageTests(FitTestBase):
    def _record(self, layer_path):
        return {
            "schema_version": "1.0",
            "job_id": "gen_test123",
            "backend": "mock",
            "outputs": [{
                "filename": "gen_test123_v0.png",
                "seed": 42,
                "size_bytes": Path(layer_path).stat().st_size,
                "sha256": sha256(layer_path),
            }],
        }

    def test_generation_record_linked_by_hash(self):
        bodies = self.make_bodies(("S",))
        tops = layer_file(self.root / "gen_test123_v0.png",
                          pixels={(6, 6): (0, 255, 0, 255)})
        manifest = fit_layers(
            bodies, [{"slot": "tops", "path": str(tops)}], self.out,
            generation={"record": self._record(tops), "slot": "tops"})
        gen = manifest["generation"]
        self.assertEqual(gen["job_id"], "gen_test123")
        self.assertEqual(gen["output_sha256"], sha256(tops))
        self.assertEqual(gen["output_filename"], "gen_test123_v0.png")
        self.assertEqual(gen["backend"], "mock")

    def test_generation_hash_mismatch_refused(self):
        bodies = self.make_bodies(("S",))
        tops = layer_file(self.root / "tp.png",
                          pixels={(6, 6): (0, 255, 0, 255)})
        other = layer_file(self.root / "other.png",
                           pixels={(1, 1): (9, 9, 9, 255)})
        record = self._record(other)  # hash of a DIFFERENT file
        with self.assertRaises(FittingError):
            fit_layers(
                bodies, [{"slot": "tops", "path": str(tops)}], self.out,
                generation={"record": record, "slot": "tops"})


class DiscoveryAndExtractTests(FitTestBase):
    def test_discover_bodies_by_direction_token(self):
        self.make_bodies(("S", "SE", "W"))
        found, _dup = discover_bodies(self.body_dir)
        self.assertEqual(sorted(found), ["S", "SE", "W"])

    def test_discover_bodies_by_prompt_index(self):
        for i in range(3):
            body_file(self.body_dir / f"p0{i}_slug_s0.png")
        found, _dup = discover_bodies(
            self.body_dir, directions=list(DIRECTIONS))
        self.assertEqual(sorted(found), ["E", "S", "SE"])

    def test_extract_layer_reuse_round_trip(self):
        body = body_file(self.root / "body.png")
        worn_img = Image.open(body).convert("RGBA")
        for x in range(6, 9):
            for y in range(6, 9):
                worn_img.putpixel((x, y), (255, 0, 0, 255))
        worn = self.root / "worn.png"
        worn_img.save(worn)
        before = sha256(body)
        layer = extract_layer(worn, body, thresh=28)
        self.assertEqual(layer.getpixel((7, 7)), (255, 0, 0, 255))
        self.assertEqual(layer.getpixel((5, 5)), (0, 0, 0, 0))
        self.assertEqual(sha256(body), before)  # original untouched


if __name__ == "__main__":
    unittest.main()
