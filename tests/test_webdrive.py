"""Unit tests for the Plushy-AI 2.0 web-drive output saving.

Stdlib unittest only. The web-drive target in these tests is a
plain temp folder standing in for a synced web-drive folder (the
module itself only ever mirrors into a folder; the drive client
does the uploading). PLUSHY_MOCK is forced on before any pipeline
import, matching tests/test_studio2.py.

Run: PLUSHY_MOCK=1 python3 -m unittest tests.test_webdrive
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["PLUSHY_MOCK"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from studio2 import Studio2Service  # noqa: E402
from studio2 import webdrive  # noqa: E402


class _Env:
    """Temporarily set PLUSHY_WEBDRIVE_DIR."""

    def __init__(self, value):
        self.value = value

    def __enter__(self):
        self._old = os.environ.get(webdrive.ENV_VAR)
        if self.value is None:
            os.environ.pop(webdrive.ENV_VAR, None)
        else:
            os.environ[webdrive.ENV_VAR] = str(self.value)

    def __exit__(self, *exc):
        if self._old is None:
            os.environ.pop(webdrive.ENV_VAR, None)
        else:
            os.environ[webdrive.ENV_VAR] = self._old


class MirrorTreeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.src = base / "src"
        self.dst = base / "dst"
        (self.src / "sub").mkdir(parents=True)
        (self.src / "a.png").write_bytes(b"aaaa")
        (self.src / "sub" / "b.png").write_bytes(b"bbbbbb")

    def test_mirror_copies_everything(self):
        report = webdrive.mirror_tree(self.src, self.dst)
        self.assertEqual(report["copied_count"], 2)
        self.assertEqual((self.dst / "a.png").read_bytes(), b"aaaa")
        self.assertEqual((self.dst / "sub" / "b.png").read_bytes(),
                         b"bbbbbb")

    def test_second_mirror_is_idempotent(self):
        webdrive.mirror_tree(self.src, self.dst)
        report = webdrive.mirror_tree(self.src, self.dst)
        self.assertEqual(report["copied_count"], 0)
        self.assertEqual(report["skipped_unchanged"], 2)

    def test_changed_file_is_recopied(self):
        webdrive.mirror_tree(self.src, self.dst)
        (self.src / "a.png").write_bytes(b"aaaa-CHANGED")
        report = webdrive.mirror_tree(self.src, self.dst)
        self.assertEqual(report["copied"], ["a.png"])
        self.assertEqual((self.dst / "a.png").read_bytes(),
                         b"aaaa-CHANGED")


class SyncTreesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.src = base / "src"
        self.src.mkdir()
        (self.src / "x.png").write_bytes(b"xx")
        self.drive = base / "drive"

    def test_disabled_without_env(self):
        with _Env(None):
            report = webdrive.sync_trees([(self.src, "out")])
        self.assertEqual(report["status"], "disabled")
        self.assertFalse(self.drive.exists())

    def test_sync_writes_files_and_manifest(self):
        with _Env(self.drive):
            report = webdrive.sync_trees([(self.src, "out")])
        self.assertEqual(report["status"], "ok")
        self.assertEqual(
            (self.drive / "out" / "x.png").read_bytes(), b"xx")
        manifest = json.loads(
            (self.drive / webdrive.MANIFEST_NAME).read_text())
        self.assertEqual(manifest["schema_version"],
                         webdrive.SCHEMA_VERSION)
        self.assertEqual(manifest["sections"][0]["copied"], ["x.png"])


class ServiceHookTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.svc = Studio2Service(base / "data")
        self.drive = base / "drive"

    def test_sync_method_reports_disabled_by_default(self):
        with _Env(None):
            report = self.svc.sync_to_webdrive()
        self.assertEqual(report["status"], "disabled")

    def test_sync_method_mirrors_service_root(self):
        marker = self.svc.root / "generated" / "keep.png"
        marker.write_bytes(b"keep")
        with _Env(self.drive):
            report = self.svc.sync_to_webdrive()
        self.assertEqual(report["status"], "ok")
        mirrored = (self.drive / "plushy-ai-2.0" / "studio2_data" /
                    "generated" / "keep.png")
        self.assertEqual(mirrored.read_bytes(), b"keep")

    def _completed_job(self):
        rec = self.svc.analyze_reference_upload(
            _png_bytes(partial=True), "ref.png", category="Top")
        job = self.svc.submit_generation(
            {"prompt": "a red top", "category": "Top", "seed": 3,
             "variations": 2, "size": 32,
             "reference_id": rec["reference_id"]})
        self.assertEqual(job["status"], "completed")
        return job

    def test_export_carries_webdrive_report_when_enabled(self):
        job = self._completed_job()
        with _Env(self.drive):
            exp = self.svc.export_generation(job["job_id"])
        self.assertEqual(exp["webdrive"]["status"], "ok")
        mirrored_export = (self.drive / "plushy-ai-2.0" /
                           "studio2_data" / exp["export_dir"])
        self.assertTrue(mirrored_export.is_dir())
        self.assertTrue(any(mirrored_export.rglob("*.png")))

    def test_export_still_works_when_webdrive_disabled(self):
        job = self._completed_job()
        with _Env(None):
            exp = self.svc.export_generation(job["job_id"])
        self.assertEqual(exp["manifest"]["status"], "ok")
        self.assertEqual(exp["webdrive"]["status"], "disabled")
        self.assertFalse(self.drive.exists())


def _png_bytes(size=(32, 32), partial=False):
    import io

    from PIL import Image, ImageDraw
    img = Image.new("RGBA", size, (0, 0, 0, 0) if partial
                    else (200, 50, 50, 255))
    if partial:
        ImageDraw.Draw(img).rectangle([5, 5, 20, 20],
                                      fill=(200, 50, 50, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


if __name__ == "__main__":
    unittest.main()
