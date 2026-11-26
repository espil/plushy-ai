"""Tests for the switchable 3D backend (fast SF3D / quality Hunyuan).

Stdlib unittest only. PLUSHY_MOCK is forced on before any pipeline
import, so every conversion here is the library's stamped mock
placeholder - which is exactly what these tests verify: that the
QUALITY backend is selectable (env config, constructor argument,
and through the Studio 2.0 service's model3d jobs), that its mock
output is honestly labelled (a *_MOCK.glb whose sidecar says
mock=true AND backend="hunyuan"), and that the default backend is
still the fast SF3D with unchanged labelling.

No GPU, no Docker, no engine venvs: with mock off these tests do
not run the real engines at all.

Run: PLUSHY_MOCK=1 python3 -m unittest tests.test_model3d_backend
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock as unittest_mock

os.environ["PLUSHY_MOCK"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

import pipeline_3d  # noqa: E402
from pipeline_3d import Model3DPipeline  # noqa: E402
from studio2 import Studio2Service  # noqa: E402


def _image(path: Path) -> Path:
    Image.new("RGB", (16, 16), (180, 60, 60)).save(path)
    return path


class BackendSelectionTests(unittest.TestCase):
    def test_default_backend_is_fast_sf3d(self):
        with unittest_mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PLUSHY_3D_BACKEND", None)
            self.assertEqual(pipeline_3d.selected_backend(), "sf3d")
            self.assertEqual(Model3DPipeline().backend, "sf3d")

    def test_env_selects_quality_backend(self):
        with unittest_mock.patch.dict(
                os.environ, {"PLUSHY_3D_BACKEND": "hunyuan"}):
            self.assertEqual(pipeline_3d.selected_backend(), "hunyuan")
            self.assertEqual(Model3DPipeline().backend, "hunyuan")

    def test_unknown_backend_env_is_a_loud_error(self):
        with unittest_mock.patch.dict(
                os.environ, {"PLUSHY_3D_BACKEND": "meshy"}):
            with self.assertRaises(ValueError):
                pipeline_3d.selected_backend()

    def test_constructor_rejects_unknown_backend(self):
        with self.assertRaises(ValueError):
            Model3DPipeline(backend="meshy")

    def test_engine_labels(self):
        self.assertEqual(
            pipeline_3d.backend_engine_label("sf3d"), "sf3d")
        self.assertEqual(
            pipeline_3d.backend_engine_label("hunyuan"),
            "hunyuan3d-2mini")


class MockLabellingTests(unittest.TestCase):
    """The mock rule, applied to the quality backend: output is a
    *_MOCK.glb and its sidecar says mock=true with the backend it
    was requested under - never presented as a real Hunyuan model."""

    def _convert(self, backend):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        src = _image(root / "in.png")
        pipe = Model3DPipeline(backend=backend)
        actual, stats = pipe.image_to_glb(src, root / "out.glb")
        sidecar = json.loads(
            Path(str(actual) + ".json").read_text(encoding="utf-8"))
        return actual, stats, sidecar

    def test_quality_backend_mock_is_labelled(self):
        actual, stats, sidecar = self._convert("hunyuan")
        self.assertTrue(actual.name.endswith("_MOCK.glb"))
        self.assertTrue(stats["mock"])
        self.assertEqual(stats["engine"], "mock")
        self.assertEqual(stats["backend"], "hunyuan")
        self.assertTrue(sidecar["mock"])
        self.assertEqual(sidecar["backend"], "hunyuan")

    def test_fast_backend_mock_labelling_unchanged(self):
        actual, stats, sidecar = self._convert("sf3d")
        self.assertTrue(actual.name.endswith("_MOCK.glb"))
        self.assertTrue(stats["mock"])
        self.assertEqual(stats["backend"], "sf3d")
        self.assertEqual(sidecar["backend"], "sf3d")


class ServiceModel3DTests(unittest.TestCase):
    """The service wiring: model3d jobs delegate to pipeline_3d the
    way generation jobs delegate to Phase 3, backend label included."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.svc = Studio2Service(self._tmp.name)
        src = Path(self._tmp.name) / "references" / "house.png"
        _image(src)
        self.source = "references/house.png"

    def test_health_reports_backend_and_mock(self):
        health = self.svc.model3d_health()
        self.assertTrue(health["mock"])
        self.assertEqual(health["backend"], "sf3d")
        self.assertEqual(health["engine"], "sf3d")
        self.assertIn("hunyuan", health["backends"])
        boot = self.svc.bootstrap()
        self.assertEqual(boot["model3d"]["backend"], "sf3d")

    def test_quality_job_completes_mock_labelled(self):
        view = self.svc.submit_model3d(
            {"source": self.source, "backend": "quality"})
        self.assertEqual(view["kind"], "model3d")
        self.assertEqual(view["status"], "completed")
        # The registry label is honest about mock mode...
        self.assertEqual(view["backend"], "mock")
        result = view["result"]
        # ...and the pipeline stats name the requested backend.
        self.assertTrue(result["mock"])
        self.assertEqual(result["backend"], "hunyuan")
        out = Path(self._tmp.name) / result["output_files"][0]
        self.assertTrue(out.name.endswith("_MOCK.glb"))
        self.assertTrue(out.exists())

    def test_default_job_uses_fast_backend(self):
        view = self.svc.submit_model3d({"source": self.source})
        self.assertEqual(view["status"], "completed")
        self.assertEqual(view["result"]["backend"], "sf3d")

    def test_unknown_backend_refused_before_queueing(self):
        from studio2 import Studio2Error
        with self.assertRaises(Studio2Error):
            self.svc.create_model3d_job(
                {"source": self.source, "backend": "meshy"})

    def test_missing_source_refused(self):
        from studio2 import Studio2Error
        with self.assertRaises(Studio2Error):
            self.svc.create_model3d_job(
                {"source": "references/nope.png",
                 "backend": "hunyuan"})


if __name__ == "__main__":
    unittest.main()
