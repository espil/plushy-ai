"""Unit tests for the Plushy-AI 2.0 Studio service layer (Phase 6).

Stdlib unittest only, and NO FastAPI: the service layer is
framework-free by design, so these tests exercise the whole 2.0
workflow (upload -> analyze -> mask suggest + confirm -> generate
job -> status poll -> compare -> fit -> export -> history) without
importing studio2.router or studio2_server. PLUSHY_MOCK is forced
on before any pipeline import, so every generation here is the
procedural mock backend and every job record honestly says so.

Run: PLUSHY_MOCK=1 python3 -m unittest tests.test_studio2
"""
import io
import os
import re
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

os.environ["PLUSHY_MOCK"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw  # noqa: E402

from studio2 import Studio2Error, Studio2Service  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def png_bytes(size=(32, 32), color=(200, 50, 50, 255), partial=False):
    img = Image.new("RGBA", size, (0, 0, 0, 0) if partial else color)
    if partial:
        ImageDraw.Draw(img).rectangle([5, 5, 20, 20], fill=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class ServiceFlowTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.svc = Studio2Service(self._tmp.name)

    def _reference(self, category="Top"):
        return self.svc.analyze_reference_upload(
            png_bytes(partial=True), "ref.png", category=category)

    def _confirmed_mask(self, ref_id):
        return self.svc.save_mask(
            ref_id,
            rectangles=[{"x": 2, "y": 2, "width": 10, "height": 10,
                         "op": "add"}],
            confirmed=True, category="Top")

    def _generation_job(self, **extra):
        params = {"prompt": "a red top", "category": "Top", "seed": 3,
                  "variations": 2, "size": 32}
        params.update(extra)
        return self.svc.submit_generation(params)

    # -- bootstrap --------------------------------------------------------

    def test_bootstrap_categories_and_profiles(self):
        boot = self.svc.bootstrap()
        self.assertEqual(len(boot["categories"]), 10)
        self.assertIn("Top", boot["categories"])
        profiles = {p["profile_id"]: p for p in boot["profiles"]}
        self.assertFalse(profiles["pixel"]["enabled"])
        self.assertTrue(profiles["pixel"]["disabled_reason"])
        self.assertFalse(boot["inpainting"]["supported"])

    # -- Phase 1 through the service ----------------------------------------

    def test_analyze_asset_and_get_asset(self):
        out = self.svc.analyze_asset(png_bytes(), "thing.png")
        record = self.svc.get_asset(out["asset_id"])
        self.assertEqual(record["canvas"]["width"], 32)
        with self.assertRaises(Studio2Error) as cm:
            self.svc.get_asset("nope")
        self.assertEqual(cm.exception.status, 404)

    def test_analyze_asset_rejects_bad_suffix_and_corrupt(self):
        with self.assertRaises(Studio2Error):
            self.svc.analyze_asset(b"MZ...", "evil.exe")
        with self.assertRaises(Studio2Error):
            self.svc.analyze_asset(b"not an image", "thing.png")

    # -- Phase 2 through the service ------------------------------------------

    def test_reference_upload_validation_reused(self):
        # A JPEG renamed to .png must be refused by the Phase 2
        # content validation the service delegates to.
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, format="JPEG")
        with self.assertRaises(Studio2Error):
            self.svc.analyze_reference_upload(buf.getvalue(), "fake.png")
        with self.assertRaises(Studio2Error):
            self.svc.analyze_reference_upload(
                png_bytes(), "ref.png", category="Bogus")

    def test_suggestion_is_never_a_target(self):
        rec = self._reference()
        sug = self.svc.suggest_mask(rec["reference_id"])
        self.assertFalse(sug["confirmed"])
        self.assertEqual(sug["bounds"],
                         {"x": 5, "y": 5, "width": 16, "height": 16})
        # Saving the same area UNCONFIRMED still yields no target.
        unconfirmed = self.svc.save_mask(
            rec["reference_id"],
            rectangles=[{"x": 5, "y": 5, "width": 16, "height": 16}],
            confirmed=False, category="Top")
        self.assertIsNone(unconfirmed["generation_target"])
        # Only a confirmed, non-empty save becomes a target.
        confirmed = self._confirmed_mask(rec["reference_id"])
        self.assertIsNotNone(confirmed["generation_target"])
        self.assertEqual(confirmed["generation_target"]["bounds"],
                         {"x": 2, "y": 2, "width": 10, "height": 10})

    def test_mask_remove_and_size_rules(self):
        rec = self._reference()
        mask = self.svc.save_mask(
            rec["reference_id"],
            rectangles=[
                {"x": 0, "y": 0, "width": 20, "height": 20, "op": "add"},
                {"x": 0, "y": 0, "width": 20, "height": 20,
                 "op": "remove"},
            ], confirmed=True, category="Top")
        self.assertEqual(mask["pixel_count"], 0)
        self.assertIsNone(mask["generation_target"])  # confirmed but empty
        with self.assertRaises(Studio2Error):
            self.svc.save_mask(
                rec["reference_id"],
                rectangles=[{"x": 30, "y": 30, "width": 10,
                             "height": 10}],
                confirmed=True, category="Top")

    # -- Phase 3 jobs -----------------------------------------------------------

    def test_end_to_end_flow(self):
        rec = self._reference()
        mask = self._confirmed_mask(rec["reference_id"])
        view = self.svc.create_generation_job({
            "prompt": "a red top", "category": "Top", "seed": 3,
            "variations": 2, "size": 32,
            "reference_id": rec["reference_id"],
            "claim_region": True, "mask_id": mask["mask_id"],
        })
        self.assertEqual(view["status"], "queued")
        done = self.svc.run_generation_job(view["job_id"])
        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["progress"], 1.0)
        self.assertEqual(done["backend"], "mock")
        result = done["result"]
        self.assertEqual(result["backend"], "mock")
        self.assertIsNotNone(result["region"])
        self.assertEqual(len(result["outputs"]), 2)
        self.assertEqual([o["seed"] for o in result["outputs"]], [3, 4])
        for rel in result["output_files"]:
            self.assertTrue(self.svc.resolve_file(rel).exists())
        # History shows the job with its parameters and mock backend.
        history = self.svc.list_jobs()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["params"]["prompt"], "a red top")
        self.assertEqual(history[0]["backend"], "mock")

    def test_text_only_generation_needs_no_mask(self):
        # 64px: the 1.0 mock backend's procedural drawing cannot
        # render its placeholder below that size (its own limit).
        done = self._generation_job(size=64)
        self.assertEqual(done["status"], "completed")
        self.assertIsNone(done["result"]["region"])
        self.assertEqual(done["result"]["mode"], "text")

    def test_job_status_transitions_and_unknown_job(self):
        view = self.svc.create_generation_job(
            {"prompt": "a hat", "category": "Accessory", "size": 32})
        self.assertEqual(view["status"], "queued")
        self.assertIsNone(view["elapsed_sec"])
        cancelled = self.svc.cancel_job(view["job_id"])
        self.assertEqual(cancelled["status"], "cancelled")
        # A cancelled job never runs.
        after = self.svc.run_generation_job(view["job_id"])
        self.assertEqual(after["status"], "cancelled")
        with self.assertRaises(Studio2Error) as cm:
            self.svc.get_job("sjob_missing")
        self.assertEqual(cm.exception.status, 404)

    def test_failed_job_records_error(self):
        # A failure inside the Phase 3 call must land in the registry
        # as status "failed" with the error recorded, not raise.
        view = self.svc.create_generation_job(
            {"prompt": "a hat", "category": "Accessory", "size": 32,
             "reference_id": self._reference()["reference_id"]})
        entry = self.svc._references[view["params"]["reference_id"]]
        entry["path"] = entry["path"].with_name("gone.png")
        done = self.svc.run_generation_job(view["job_id"])
        self.assertEqual(done["status"], "failed")
        self.assertTrue(done["error"])
        self.assertEqual(done["message"], "failed")

    def test_bad_category_and_disabled_profile_refused(self):
        with self.assertRaises(Studio2Error):
            self.svc.create_generation_job(
                {"prompt": "x", "category": "Bogus"})
        with self.assertRaises(Studio2Error) as cm:
            self.svc.create_generation_job(
                {"prompt": "x", "profile_id": "pixel"})
        self.assertIn("disabled", str(cm.exception))

    def test_unconfirmed_region_generation_refused(self):
        rec = self._reference()
        unconfirmed = self.svc.save_mask(
            rec["reference_id"],
            rectangles=[{"x": 1, "y": 1, "width": 5, "height": 5}],
            confirmed=False, category="Top")
        base = {"prompt": "x", "category": "Top",
                "reference_id": rec["reference_id"],
                "claim_region": True}
        with self.assertRaises(Studio2Error):
            self.svc.create_generation_job(base)  # no mask at all
        with self.assertRaises(Studio2Error):
            self.svc.create_generation_job(
                {**base, "mask_id": unconfirmed["mask_id"]})
        with self.assertRaises(Studio2Error):
            self.svc.create_generation_job(
                {"prompt": "x", "claim_region": True})  # no reference

    def test_inpaint_request_refused(self):
        with self.assertRaises(Studio2Error) as cm:
            self.svc.create_generation_job(
                {"prompt": "x", "inpaint": True})
        self.assertIn("unsupported", str(cm.exception))

    # -- compare / fit / export ---------------------------------------------------

    def test_compare_fit_export_flow(self):
        rec = self._reference()
        job = self._generation_job(reference_id=rec["reference_id"])
        self.assertEqual(job["status"], "completed")

        cmp_rec = self.svc.compare(job["job_id"])
        self.assertTrue(cmp_rec["size_match"])
        self.assertEqual(cmp_rec["generated"]["canvas"]["width"], 32)
        self.assertTrue(self.svc.resolve_file(
            cmp_rec["side_by_side"]["file"]).exists())

        fit = self.svc.compose_paperdoll(
            {"reference_id": rec["reference_id"]},
            {"job_id": job["job_id"]}, "tops")
        self.assertEqual(fit["summary"],
                         {"ok": 1, "missing": 7, "needs_review": 0})
        s_entry = next(e for e in fit["entries"]
                       if e["direction"] == "S")
        self.assertEqual(s_entry["status"], "ok")
        self.assertTrue(self.svc.resolve_file(
            s_entry["outputs"]["composite"]["file"]).exists())
        # The fit proves the Phase 3 linkage by sha256.
        self.assertEqual(fit["generation"]["job_id"],
                         job["result"]["job_id"])

        exp = self.svc.export_generation(job["job_id"], aseprite=True,
                                         asset_id="flow")
        self.assertEqual(exp["manifest"]["status"], "ok")
        self.assertEqual(
            exp["manifest"]["outputs"]["aseprite"]["status"], "ok")
        self.assertEqual(len(exp["manifest"]["outputs"]["png_copies"]), 2)

        exp_fit = self.svc.export_fitting(fit["fit_id"])
        # 7 directions honestly missing -> needs_review, sheet exists.
        self.assertEqual(exp_fit["manifest"]["status"], "needs_review")
        self.assertEqual(
            exp_fit["manifest"]["validation"]["directions_missing"], 7)
        self.assertIsNotNone(
            exp_fit["manifest"]["outputs"]["sprite_sheet"])

    def test_resolve_file_confined_to_root(self):
        rec = self._reference()
        stored = "references/" + rec["source"]["stored_filename"]
        self.assertTrue(self.svc.resolve_file(stored).exists())
        for bad in ("../app.py", "/etc/passwd", "references/../../app.py",
                    "references/missing.png", ""):
            with self.assertRaises(Studio2Error, msg=bad):
                self.svc.resolve_file(bad)


class Studio2HtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (REPO / "static" / "studio2.html").read_text(
            encoding="utf-8")

    def test_all_nine_screens_present(self):
        for name in ("input", "category", "region", "standard",
                     "generate", "compare", "paperdoll", "export",
                     "history"):
            self.assertIn(f'id="screen-{name}"', self.html)

    def test_fetch_calls_target_new_endpoints_only(self):
        for ep in ("/api/assets/analyze", "/api/reference/analyze",
                   "/api/masks", "/api/assets/generate", "/api/jobs/",
                   "/api/paperdoll/compose", "/api/export",
                   "/api/compare", "/api/studio2/bootstrap",
                   "/api/studio2/files"):
            self.assertIn(ep, self.html)
        # None of the 1.0 generation endpoints are called.
        for old in ("/api/sprite", "/api/img2img", "/api/model3d",
                    "/api/status/", "/api/result/", "/api/outputs"):
            self.assertNotIn(old, self.html)

    def test_no_innerhtml_and_no_external_resources(self):
        self.assertNotIn("innerHTML", self.html)
        self.assertIsNone(
            re.search(r"(?:src|href)\s*=\s*[\"']https?://", self.html))
        self.assertNotIn("cdn", self.html.lower())

    def test_balanced_tags_and_dom_ids_exist(self):
        class Checker(HTMLParser):
            VOID = {"meta", "link", "input", "img", "br", "hr",
                    "source"}

            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.stack = []
                self.ids = set()
                self.errors = []

            def handle_starttag(self, tag, attrs):
                d = dict(attrs)
                if "id" in d:
                    self.ids.add(d["id"])
                if tag not in self.VOID:
                    self.stack.append(tag)

            def handle_endtag(self, tag):
                if tag in self.VOID:
                    return
                if not self.stack or self.stack[-1] != tag:
                    self.errors.append(tag)
                else:
                    self.stack.pop()

        checker = Checker()
        checker.feed(self.html)
        self.assertEqual(checker.errors, [])
        self.assertEqual(checker.stack, [])
        targets = set(re.findall(r"\$\('([^']+)'\)", self.html))
        self.assertTrue(targets)
        self.assertEqual(targets - checker.ids, set())


if __name__ == "__main__":
    unittest.main()
