"""Unit tests for the Plushy-AI 2.0 Asset Generator (Phase 3).

Stdlib unittest only. These tests MUST run against the pipeline's
procedural mock backend: PLUSHY_MOCK is forced on below before any
pipeline import happens (the generator imports pipeline_sprite
lazily), so no GPU, torch or model download is involved, and every
job record produced here honestly states backend "mock".

Run: PLUSHY_MOCK=1 python3 -m unittest tests.test_generator
"""
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["PLUSHY_MOCK"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from generator import (  # noqa: E402
    CATEGORY_TEMPLATES,
    GeneratorError,
    backend_name,
    compare_with_baseline,
    compose_prompt,
    derive_seed,
    get_profile,
    inpainting_status,
    list_profiles,
    run_generation,
)
from reference import (  # noqa: E402
    CATEGORIES,
    MaskCanvas,
    analyze_reference,
    build_mask_record,
)


def png_file(path, size=(24, 24), color=(40, 160, 60, 255)):
    img = Image.new("RGBA", size, color)
    img.save(path, format="PNG")
    return path


class ProfileTests(unittest.TestCase):
    REQUIRED = ("profile_id", "rendering_mode", "pipeline_style",
                "enabled", "disabled_reason", "target_size",
                "palette_limit", "outline", "transparent_background",
                "resize_sampling", "post_processing", "style_profile")

    def test_profile_data_structure(self):
        profiles = list_profiles()
        self.assertGreaterEqual(len(profiles), 5)
        for p in profiles:
            for key in self.REQUIRED:
                self.assertIn(key, p)
            self.assertIn("width", p["target_size"])
            self.assertIn("height", p["target_size"])

    def test_enabled_profiles_map_to_real_pipeline_styles(self):
        for p in list_profiles():
            if p["enabled"]:
                self.assertIn(p["pipeline_style"],
                              ("default", "2.5d", "3d", "chibi"))
                self.assertIsNone(p["disabled_reason"])

    def test_disabled_modes_carry_reasons(self):
        pixel = get_profile("pixel")
        self.assertFalse(pixel["enabled"])
        self.assertIsNone(pixel["pipeline_style"])
        self.assertTrue(pixel["disabled_reason"])
        self.assertEqual(pixel["rendering_mode"], "pixel")
        for p in list_profiles():
            if not p["enabled"]:
                self.assertTrue(p["disabled_reason"])

    def test_unmeasured_style_values_stay_null(self):
        for p in list_profiles():
            sp = p["style_profile"]
            self.assertIsNone(sp["pixel_scale"])
            self.assertIsNone(sp["outline"])
            self.assertIsNone(sp["antialiasing"])
            self.assertEqual(sp["asset_standard_schema_version"], "1.0")

    def test_unknown_profile_raises(self):
        with self.assertRaises(GeneratorError):
            get_profile("no-such-profile")

    def test_disabled_profile_generation_refused(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(GeneratorError):
                run_generation("a hat", d, profile_id="pixel")


class TemplateTests(unittest.TestCase):
    def test_template_for_every_category(self):
        self.assertEqual(set(CATEGORY_TEMPLATES), set(CATEGORIES))
        self.assertEqual(len(CATEGORY_TEMPLATES), 10)

    def test_composition_preserves_user_prompt_verbatim(self):
        user = "fluffy RED hoodie!! (my exact words)"
        composed = compose_prompt("Top", user)
        self.assertIn(user, composed)
        self.assertNotEqual(composed, user)

    def test_unknown_category_and_empty_prompt_raise(self):
        with self.assertRaises(Exception):
            compose_prompt("Weaponn", "a sword")
        with self.assertRaises(GeneratorError):
            compose_prompt("Top", "   ")


class SeedTests(unittest.TestCase):
    def test_seed_derivation_is_deterministic(self):
        self.assertEqual([derive_seed(100, i) for i in range(3)],
                         [100, 101, 102])
        self.assertEqual(derive_seed(7, 0), 7)
        self.assertEqual(derive_seed(-5, 2), -3)
        with self.assertRaises(GeneratorError):
            derive_seed(0, -1)


class JobRecordTests(unittest.TestCase):
    def test_text_job_record_shape_and_backend_honesty(self):
        with tempfile.TemporaryDirectory() as d:
            rec = run_generation("a pine tree", d, seed=42, variations=2,
                                 width=64, height=64)
            self.assertEqual(rec["schema_version"], "1.0")
            self.assertEqual(rec["status"], "completed")
            self.assertEqual(rec["mode"], "text")
            self.assertEqual(rec["backend"], "mock")
            self.assertEqual(backend_name(), "mock")
            self.assertEqual(rec["seed"], 42)
            self.assertEqual(rec["seeds"], [42, 43])
            self.assertIsNone(rec["region"])
            self.assertIsNone(rec["reference"])
            self.assertIsNone(rec["strength"])
            self.assertEqual(
                rec["asset_standard_schema_version"], "1.0")
            self.assertFalse(rec["inpainting"]["supported"])
            self.assertEqual(len(rec["outputs"]), 2)
            job_json = Path(d) / f"{rec['job_id']}.job.json"
            self.assertTrue(job_json.exists())
            on_disk = json.loads(job_json.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["backend"], "mock")
            self.assertEqual(on_disk["job_id"], rec["job_id"])

    def test_variations_produce_n_outputs_with_safe_names(self):
        with tempfile.TemporaryDirectory() as d:
            rec = run_generation("a sword", d, category="Weapon",
                                 seed=5, variations=3, width=48,
                                 height=48)
            self.assertEqual(len(rec["outputs"]), 3)
            self.assertEqual(rec["prompt_user"], "a sword")
            self.assertIn("a sword", rec["prompt_composed"])
            for i, o in enumerate(rec["outputs"]):
                self.assertEqual(o["filename"],
                                 f"{rec['job_id']}_v{i}.png")
                self.assertEqual(o["seed"], 5 + i)
                path = Path(d) / o["filename"]
                self.assertTrue(path.exists())
                self.assertEqual(
                    o["sha256"],
                    hashlib.sha256(path.read_bytes()).hexdigest())
                with Image.open(path) as img:
                    self.assertEqual(img.size, (48, 48))

    def test_inpainting_status_and_request_refusal(self):
        st = inpainting_status()
        self.assertFalse(st["supported"])
        self.assertEqual(st["status"], "unsupported")
        self.assertIn("mask", st["reason"])
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(GeneratorError):
                run_generation("a hat", d, inpaint=True)


class GatingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.ref_path = png_file(self.dir / "ref.png", size=(24, 24))
        self.ref = analyze_reference(self.ref_path, category="Top")
        self.out = self.dir / "out"

    def tearDown(self):
        self._tmp.cleanup()

    def _confirmed_mask_record(self):
        mask = MaskCanvas(24, 24)
        mask.add_rectangle(2, 3, 10, 8)
        return build_mask_record(self.ref, mask, confirmed=True)

    def test_region_claim_without_mask_refused(self):
        with self.assertRaises(GeneratorError):
            run_generation("blue version", self.out,
                           reference_record=self.ref,
                           reference_image_path=self.ref_path,
                           claim_region=True, mask_record=None)

    def test_region_claim_with_unconfirmed_mask_refused(self):
        mask = MaskCanvas(24, 24)
        mask.add_rectangle(0, 0, 5, 5)
        unconfirmed = build_mask_record(self.ref, mask, confirmed=False)
        with self.assertRaises(GeneratorError):
            run_generation("blue version", self.out,
                           reference_record=self.ref,
                           reference_image_path=self.ref_path,
                           claim_region=True, mask_record=unconfirmed)

    def test_region_claim_with_confirmed_empty_mask_refused(self):
        empty = build_mask_record(self.ref, MaskCanvas(24, 24),
                                  confirmed=True)
        with self.assertRaises(GeneratorError):
            run_generation("blue version", self.out,
                           reference_record=self.ref,
                           reference_image_path=self.ref_path,
                           claim_region=True, mask_record=empty)

    def test_whole_image_img2img_allowed_region_null(self):
        rec = run_generation("blue version", self.out, category="Top",
                             reference_record=self.ref,
                             reference_image_path=self.ref_path,
                             width=24, height=24)
        self.assertEqual(rec["mode"], "img2img")
        self.assertIsNone(rec["region"])
        self.assertEqual(rec["reference"]["reference_id"],
                         self.ref["reference_id"])
        self.assertEqual(rec["reference"]["sha256"],
                         self.ref["source"]["sha256"])
        self.assertEqual(rec["strength"], 0.6)
        self.assertEqual(len(rec["outputs"]), 1)

    def test_region_claim_with_confirmed_mask_allowed(self):
        mrec = self._confirmed_mask_record()
        rec = run_generation("blue version", self.out,
                             reference_record=self.ref,
                             reference_image_path=self.ref_path,
                             claim_region=True, mask_record=mrec,
                             width=24, height=24)
        self.assertIsNotNone(rec["region"])
        self.assertEqual(rec["region"]["bounds"],
                         {"x": 2, "y": 3, "width": 10, "height": 8})
        self.assertEqual(rec["region"]["mask_sha256"],
                         mrec["mask_sha256"])

    def test_original_reference_file_unmodified(self):
        before = hashlib.sha256(self.ref_path.read_bytes()).hexdigest()
        run_generation("blue version", self.out,
                       reference_record=self.ref,
                       reference_image_path=self.ref_path,
                       width=24, height=24)
        after = hashlib.sha256(self.ref_path.read_bytes()).hexdigest()
        self.assertEqual(before, after)


class CompareTests(unittest.TestCase):
    def test_compare_record_measured_facts_and_composite(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            gen = run_generation("a tree", d / "gen", seed=1,
                                 width=32, height=32)
            gen_path = d / "gen" / gen["outputs"][0]["filename"]
            baseline = png_file(d / "baseline.png", size=(32, 32))
            rec = compare_with_baseline(gen_path, baseline,
                                        out_dir=d / "cmp")
            self.assertEqual(rec["schema_version"], "1.0")
            self.assertTrue(rec["size_match"])
            self.assertEqual(rec["generated"]["canvas"]["width"], 32)
            self.assertEqual(rec["baseline"]["canvas"]["height"], 32)
            self.assertIsNotNone(rec["generated"]["content_bounds"])
            self.assertEqual(
                rec["generated"]["sha256"],
                hashlib.sha256(gen_path.read_bytes()).hexdigest())
            side = rec["side_by_side"]
            self.assertIsNotNone(side)
            self.assertEqual(side["width"], 64)
            self.assertTrue((d / "cmp" / side["filename"]).exists())
            self.assertNotIn("score", json.dumps(rec).lower())


if __name__ == "__main__":
    unittest.main()
