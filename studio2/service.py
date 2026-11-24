"""Framework-free service layer for the Plushy-AI 2.0 Studio (Phase 6).

Every heavy operation is delegated to the Phase 1-5 libraries, which
are imported - never modified, never duplicated:

  - Phase 1 `asset_standard.analyze_file`      (asset analysis)
  - Phase 2 `reference`                        (validated upload,
                                                ingestion, masks)
  - Phase 3 `generator`                        (style profiles,
                                                generation jobs,
                                                baseline comparison)
  - Phase 4 `fitting.fit_layers`               (paper-doll compose)
  - Phase 5 `exporter.export_assets`           (PNG / sheet / ASE)

This module imports NO web framework, so the whole 2.0 workflow is
testable (and usable) without FastAPI installed. The thin HTTP
adapter lives in `studio2/router.py`; the standalone entrypoint is
`studio2_server.py`.

Jobs: generation runs through an in-memory registry whose status
shape mirrors the 1.0 job shape (job_id, status, progress, message,
result, error, elapsed_sec), with the same status vocabulary
(queued / processing / completed / failed / cancelled), so the UI
can poll a long GPU job exactly like the 1.0 Studio polls
/api/status/{job_id}. In this service the work itself runs inline
when `run_generation_job` is called (the router schedules it as a
background task); the registry records every transition either way.

Backend honesty: the backend reported by Phase 3 ("mock" under
PLUSHY_MOCK=1, otherwise "sdxl") is stored on every job and in the
history - a mock placeholder is never presented as a real model
generation, in the API or in the UI.

Storage: everything the service writes lives under one root
directory (references/, masks/, generated/, compares/, fits/,
exports/, assets/). User-supplied filenames are never used as
paths: uploads go through the Phase 2 validated ingestion (safe
generated names), and every other name is service-generated.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from asset_standard import AssetAnalysisError, analyze_file
from exporter import ExportError, export_assets
from fitting import FittingError, fit_layers
from generator import GeneratorError, compare_with_baseline, get_profile, \
    list_profiles, run_generation
from reference import CATEGORIES, MaskCanvas, ReferenceError, \
    build_mask_record, generation_target, ingest_reference, save_mask, \
    suggest_mask, validate_category

SERVICE_SCHEMA_VERSION = "1.0"

JOB_STATUSES = ("queued", "processing", "completed", "failed",
                "cancelled")

_ASSET_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
                   ".ase", ".aseprite")


class Studio2Error(Exception):
    """A service-level refusal, with an HTTP-ish status for the router.

    The message is plain safe text produced by this codebase or by
    the Phase 1-5 libraries; the UI displays it with textContent.
    """

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_token(name, fallback: str) -> str:
    safe = re.sub(r"[^a-z0-9_-]+", "_", str(name).lower()).strip("_")
    return safe or fallback


# Library errors that mean "the request is invalid" (HTTP 400).
_LIBRARY_ERRORS = (ReferenceError, GeneratorError, FittingError,
                   ExportError, AssetAnalysisError)


class JobRegistry:
    """In-memory generation-job registry (1.0 status shape)."""

    def __init__(self):
        self._jobs: dict[str, dict] = {}

    def create(self, kind: str, params: dict, backend) -> dict:
        job = {
            "job_id": "sjob_" + uuid.uuid4().hex,
            "kind": kind,
            "status": "queued",
            "progress": 0.0,
            "message": "queued",
            "params": dict(params),
            "backend": backend,
            "result": None,
            "error": None,
            "created_at": _now(),
            "started_at": None,
            "finished_at": None,
            "_t_created": time.time(),
            "_t_started": None,
            "_t_finished": None,
        }
        self._jobs[job["job_id"]] = job
        return job

    def get(self, job_id: str) -> dict:
        job = self._jobs.get(job_id)
        if job is None:
            raise Studio2Error(f"unknown job_id: {job_id}", status=404)
        return job

    def transition(self, job: dict, status: str, message=None,
                   progress=None, result=None, error=None) -> dict:
        if status not in JOB_STATUSES:
            raise Studio2Error(f"unknown job status {status!r}")
        job["status"] = status
        if message is not None:
            job["message"] = message
        if progress is not None:
            job["progress"] = progress
        if result is not None:
            job["result"] = result
        if error is not None:
            job["error"] = error
        now = time.time()
        if status == "processing" and job["_t_started"] is None:
            job["_t_started"] = now
            job["started_at"] = _now()
        if status in ("completed", "failed", "cancelled"):
            job["_t_finished"] = now
            job["finished_at"] = _now()
            if status == "completed":
                job["progress"] = 1.0
        return job

    def cancel(self, job_id: str) -> dict:
        job = self.get(job_id)
        if job["status"] != "queued":
            raise Studio2Error(
                f"job {job_id} cannot be cancelled in status "
                f"{job['status']!r} (only queued jobs can)")
        return self.transition(job, "cancelled",
                               message="cancelled by user")

    def status_view(self, job: dict) -> dict:
        """The public status dict (1.0 shape plus params/history data)."""
        elapsed = None
        if job["_t_started"] is not None:
            end = job["_t_finished"] or time.time()
            elapsed = round(end - job["_t_started"], 3)
        return {
            "job_id": job["job_id"],
            "kind": job["kind"],
            "status": job["status"],
            "progress": job["progress"],
            "message": job["message"],
            "backend": job["backend"],
            "params": job["params"],
            "result": job["result"],
            "error": job["error"],
            "elapsed_sec": elapsed,
            "created_at": job["created_at"],
            "started_at": job["started_at"],
            "finished_at": job["finished_at"],
        }

    def list_views(self) -> list:
        """All jobs, newest first (the History screen's data)."""
        return [self.status_view(j) for j in
                sorted(self._jobs.values(),
                       key=lambda j: j["_t_created"], reverse=True)]


class Studio2Service:
    """The whole Phase 6 workflow over the Phase 1-5 libraries."""

    def __init__(self, root_dir):
        self.root = Path(root_dir)
        for sub in ("references", "masks", "generated", "compares",
                    "fits", "exports", "assets"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self.jobs = JobRegistry()
        self._references: dict[str, dict] = {}   # id -> {record, path}
        self._masks: dict[str, dict] = {}        # id -> {record, path}
        self._assets: dict[str, dict] = {}       # id -> standard record
        self._fits: dict[str, dict] = {}         # id -> {manifest, dir}

    # -- bootstrap ------------------------------------------------------

    def bootstrap(self) -> dict:
        """Data the UI needs on load: categories + profiles (with the
        disabled profiles' reasons) + the inpainting verdict."""
        from generator import inpainting_status

        return {
            "schema_version": SERVICE_SCHEMA_VERSION,
            "categories": list(CATEGORIES),
            "profiles": list_profiles(),
            "inpainting": inpainting_status(),
            "layer_slots": ["hair_back", "bottoms", "tops", "shoes",
                            "face", "hair_front"],
        }

    # -- Phase 1: asset analysis ----------------------------------------

    def analyze_asset(self, data: bytes, filename: str) -> dict:
        """Analyze an uploaded image/Aseprite file (POST /api/assets/analyze).

        The bytes are written under a generated safe name (the user
        filename contributes only a sanitized suffix) and analyzed
        with the Phase 1 engine. Returns {asset_id, asset_standard}.
        """
        suffix = Path(str(filename)).suffix.lower()
        if suffix not in _ASSET_SUFFIXES:
            raise Studio2Error(
                f"unsupported asset suffix {suffix!r}; expected one of "
                + ", ".join(_ASSET_SUFFIXES))
        name = "asset_" + uuid.uuid4().hex + suffix
        path = self.root / "assets" / name
        path.write_bytes(data)
        try:
            standard = analyze_file(path)
        except _LIBRARY_ERRORS as e:
            raise Studio2Error(str(e)) from e
        asset_id = standard.get("asset_id") or path.stem
        self._assets[asset_id] = standard
        return {"asset_id": asset_id, "asset_standard": standard}

    def get_asset(self, asset_id: str) -> dict:
        """Return a stored asset-standard record (GET /api/assets/{id})."""
        record = self._assets.get(asset_id)
        if record is None:
            raise Studio2Error(f"unknown asset_id: {asset_id}",
                               status=404)
        return record

    # -- Phase 2: references and masks -----------------------------------

    def analyze_reference_upload(self, data: bytes, filename: str,
                                 category=None) -> dict:
        """Validate + store + analyze a reference upload.

        Delegates entirely to Phase 2 `ingest_reference` (size,
        extension AND content validation; safe generated filename).
        """
        try:
            record = ingest_reference(data, filename,
                                      self.root / "references",
                                      category=category)
        except _LIBRARY_ERRORS as e:
            raise Studio2Error(str(e)) from e
        path = self.root / "references" / record["source"]["stored_filename"]
        self._references[record["reference_id"]] = {
            "record": record, "path": path}
        return record

    def get_reference(self, reference_id: str) -> dict:
        entry = self._references.get(reference_id)
        if entry is None:
            raise Studio2Error(f"unknown reference_id: {reference_id}",
                               status=404)
        return entry["record"]

    def _reference_entry(self, reference_id: str) -> dict:
        entry = self._references.get(reference_id)
        if entry is None:
            raise Studio2Error(f"unknown reference_id: {reference_id}",
                               status=404)
        return entry

    def suggest_mask(self, reference_id: str) -> dict:
        """Return the Phase 2 mask SUGGESTION for a reference.

        A suggestion is a proposal only: it is returned unconfirmed,
        is never stored as a generation target, and becomes usable
        only when the user saves a mask with confirmed=True.
        """
        entry = self._reference_entry(reference_id)
        try:
            canvas = suggest_mask(entry["record"])
        except _LIBRARY_ERRORS as e:
            raise Studio2Error(str(e)) from e
        return {
            "reference_id": reference_id,
            "confirmed": False,
            "suggestion": True,
            "width": canvas.width,
            "height": canvas.height,
            "bounds": canvas.bounds(),
            "pixel_count": canvas.pixel_count(),
            "note": "suggestion only - not a generation target until "
                    "the user confirms a saved mask",
        }

    def save_mask(self, reference_id: str, rectangles=None,
                  base: str = "empty", confirmed: bool = False,
                  category=None) -> dict:
        """Create/edit + save a mask (POST /api/masks).

        base: "empty" starts from a blank canvas, "suggestion" starts
        from the Phase 2 suggested mask. rectangles: a list of
        {x, y, width, height, op} edits applied in order, op "add"
        (default) or "remove" - the Phase 2 library's rectangle
        model. The mask is saved as a transparent PNG plus its
        record; the record's generation_target stays None unless
        confirmed AND non-empty (the Phase 2 gate).
        """
        entry = self._reference_entry(reference_id)
        record = entry["record"]
        standard = record.get("asset_standard") or {}
        canvas_info = standard.get("canvas") or {}
        if not canvas_info.get("width") or not canvas_info.get("height"):
            raise Studio2Error("reference record has no canvas size")
        try:
            if base == "suggestion":
                canvas = suggest_mask(record)
            elif base == "empty":
                canvas = MaskCanvas(canvas_info["width"],
                                    canvas_info["height"])
            else:
                raise Studio2Error(
                    f"mask base must be 'empty' or 'suggestion', "
                    f"got {base!r}")
            for rect in rectangles or []:
                op = rect.get("op", "add")
                args = (int(rect["x"]), int(rect["y"]),
                        int(rect["width"]), int(rect["height"]))
                if op == "add":
                    canvas.add_rectangle(*args)
                elif op == "remove":
                    canvas.remove_rectangle(*args)
                else:
                    raise Studio2Error(
                        f"rectangle op must be 'add' or 'remove', "
                        f"got {op!r}")
            mask_id = "mask_" + uuid.uuid4().hex
            path = self.root / "masks" / f"{mask_id}.png"
            mask_record = save_mask(canvas, path, record,
                                    confirmed=bool(confirmed),
                                    category=category)
        except Studio2Error:
            raise
        except _LIBRARY_ERRORS as e:
            raise Studio2Error(str(e)) from e
        except (KeyError, TypeError, ValueError) as e:
            raise Studio2Error(f"invalid rectangle: {e}") from e
        mask_record = dict(mask_record)
        mask_record["mask_id"] = mask_id
        mask_record["mask_file"] = self._rel(path)
        self._masks[mask_id] = {"record": mask_record, "path": path}
        return mask_record

    def get_mask(self, mask_id: str) -> dict:
        entry = self._masks.get(mask_id)
        if entry is None:
            raise Studio2Error(f"unknown mask_id: {mask_id}", status=404)
        return entry["record"]

    # -- Phase 3: generation jobs ----------------------------------------

    def _backend(self):
        from generator import backend_name

        try:
            return backend_name()
        except Exception:  # noqa: BLE001 - pipeline module unreadable
            return None

    def create_generation_job(self, params: dict) -> dict:
        """Validate a generation request and queue a job for it.

        Refusals that must surface BEFORE any work is queued (bad
        category, disabled profile, a claimed region without a
        confirmed non-empty Phase 2 mask target, inpainting) raise
        Studio2Error here; the job registry only ever sees valid
        requests. Returns the job's status view (status "queued").
        """
        params = dict(params or {})
        prompt = params.get("prompt")
        if not prompt or not str(prompt).strip():
            raise Studio2Error("prompt must not be empty")
        if params.get("inpaint"):
            from generator import inpainting_status

            raise Studio2Error(
                "inpainting requested but unsupported: "
                + inpainting_status()["reason"])
        category = params.get("category")
        if category is not None:
            try:
                validate_category(category)
            except _LIBRARY_ERRORS as e:
                raise Studio2Error(str(e)) from e
        profile_id = params.get("profile_id", "sprite-default")
        try:
            profile = get_profile(profile_id)
        except _LIBRARY_ERRORS as e:
            raise Studio2Error(str(e)) from e
        if not profile["enabled"]:
            raise Studio2Error(
                f"style profile {profile_id!r} is disabled: "
                + str(profile["disabled_reason"]))
        reference_id = params.get("reference_id")
        if reference_id is not None:
            self._reference_entry(reference_id)
        if params.get("claim_region"):
            if reference_id is None:
                raise Studio2Error(
                    "a target region can only be claimed for "
                    "reference-based generation")
            mask_id = params.get("mask_id")
            if not mask_id:
                raise Studio2Error(
                    "region-targeted generation refused: no mask_id "
                    "given (a confirmed, non-empty mask is required)")
            target = generation_target(self.get_mask(mask_id))
            if target is None:
                raise Studio2Error(
                    "region-targeted generation refused: the mask "
                    "is not a confirmed, non-empty generation target "
                    "(Phase 2 gate)")
            if target["reference_id"] != reference_id:
                raise Studio2Error(
                    "mask record does not belong to this reference")
        job = self.jobs.create("generation", params,
                               backend=self._backend())
        return self.jobs.status_view(job)

    def run_generation_job(self, job_id: str) -> dict:
        """Execute a queued generation job (processing -> terminal).

        Runs the Phase 3 `run_generation` into generated/<gen job
        id>/ and records its full job record as the result, so the
        backend label, region and inpainting verdict travel with it.
        """
        job = self.jobs.get(job_id)
        if job["status"] == "cancelled":
            return self.jobs.status_view(job)
        if job["status"] != "queued":
            raise Studio2Error(
                f"job {job_id} cannot run in status {job['status']!r}")
        params = job["params"]
        self.jobs.transition(job, "processing", message="generating",
                             progress=0.1)
        try:
            reference_record = None
            reference_path = None
            if params.get("reference_id") is not None:
                entry = self._reference_entry(params["reference_id"])
                reference_record = entry["record"]
                reference_path = entry["path"]
            mask_record = None
            if params.get("mask_id"):
                mask_record = self.get_mask(params["mask_id"])
            size = params.get("size")
            record = run_generation(
                params["prompt"],
                self.root / "generated",
                category=params.get("category"),
                profile_id=params.get("profile_id", "sprite-default"),
                seed=int(params.get("seed", 0)),
                variations=int(params.get("variations", 1)),
                width=int(size) if size else params.get("width"),
                height=int(size) if size else params.get("height"),
                steps=int(params.get("steps", 6)),
                negative_prompt=params.get("negative_prompt"),
                reference_record=reference_record,
                reference_image_path=reference_path,
                strength=float(params.get("strength", 0.6)),
                claim_region=bool(params.get("claim_region")),
                mask_record=mask_record,
            )
        except _LIBRARY_ERRORS as e:
            self.jobs.transition(job, "failed", message="failed",
                                 error=str(e))
            return self.jobs.status_view(job)
        result = dict(record)
        gen_dir = self.root / "generated"
        result["output_files"] = [
            self._rel(gen_dir / o["filename"]) for o in record["outputs"]]
        result["job_file"] = self._rel(
            gen_dir / record.get("job_filename", ""))
        self.jobs.transition(job, "completed", message="done",
                             result=result)
        return self.jobs.status_view(job)

    def submit_generation(self, params: dict) -> dict:
        """Create + run a generation job synchronously (tests, CLI)."""
        view = self.create_generation_job(params)
        return self.run_generation_job(view["job_id"])

    def get_job(self, job_id: str) -> dict:
        return self.jobs.status_view(self.jobs.get(job_id))

    def list_jobs(self) -> list:
        return self.jobs.list_views()

    def cancel_job(self, job_id: str) -> dict:
        return self.jobs.status_view(self.jobs.cancel(job_id))

    # -- Phase 3: comparison ----------------------------------------------

    def _generation_output_path(self, job_id: str, filename=None) -> Path:
        view = self.get_job(job_id)
        result = view.get("result")
        if not result or not result.get("outputs"):
            raise Studio2Error(
                f"job {job_id} has no generation outputs",
                status=409)
        outputs = result["outputs"]
        chosen = None
        for o in outputs:
            if filename is None or o.get("filename") == filename:
                chosen = o
                break
        if chosen is None:
            raise Studio2Error(
                f"output {filename!r} not in job {job_id}", status=404)
        return self.root / "generated" / chosen["filename"]

    def compare(self, job_id: str, baseline_reference_id=None,
                output_filename=None) -> dict:
        """Compare a generation output with a baseline (POST /api/compare).

        Baseline defaults to the job's own reference image; measured
        facts only (Phase 3 compare_with_baseline), plus the
        side-by-side composite PNG under compares/.
        """
        view = self.get_job(job_id)
        generated = self._generation_output_path(job_id, output_filename)
        baseline_id = baseline_reference_id
        if baseline_id is None:
            baseline_id = (view.get("params") or {}).get("reference_id")
        if baseline_id is None:
            raise Studio2Error(
                "no baseline: pass baseline_reference_id or use a "
                "reference-based generation job")
        baseline = self._reference_entry(baseline_id)["path"]
        try:
            record = compare_with_baseline(generated, baseline,
                                           out_dir=self.root / "compares")
        except _LIBRARY_ERRORS as e:
            raise Studio2Error(str(e)) from e
        record = dict(record)
        if record.get("side_by_side"):
            record["side_by_side"] = dict(record["side_by_side"])
            record["side_by_side"]["file"] = self._rel(
                self.root / "compares" /
                record["side_by_side"]["filename"])
        record["job_id"] = job_id
        record["baseline_reference_id"] = baseline_id
        return record

    # -- Phase 4: paper-doll compose ---------------------------------------

    def _resolve_image_spec(self, spec, what: str) -> Path:
        """Resolve {reference_id} or {job_id, filename} to a file path."""
        if not isinstance(spec, dict):
            raise Studio2Error(f"{what} must be an object with "
                               f"reference_id or job_id")
        if spec.get("reference_id"):
            return self._reference_entry(spec["reference_id"])["path"]
        if spec.get("job_id"):
            return self._generation_output_path(spec["job_id"],
                                                spec.get("filename"))
        raise Studio2Error(
            f"{what} needs a reference_id or a job_id")

    def compose_paperdoll(self, body: dict, layer: dict,
                          slot: str) -> dict:
        """Fit one generated/reference layer onto a body (compose).

        body / layer: image specs ({reference_id} or {job_id,
        filename}). The body is fitted for direction S only (the
        single-image Studio flow); the Phase 4 manifest still
        accounts for all 8 directions - the other seven are
        honestly "missing" a body. When the layer comes from a
        generation job, the Phase 4 sha256 linkage is passed so the
        fit only claims outputs it can prove.
        """
        body_path = self._resolve_image_spec(body, "body")
        layer_path = self._resolve_image_spec(layer, "layer")
        generation = None
        if isinstance(layer, dict) and layer.get("job_id"):
            view = self.get_job(layer["job_id"])
            if view.get("result"):
                generation = {"record": view["result"], "slot": slot,
                              "output": layer.get("filename")}
        fit_id = "fit_" + uuid.uuid4().hex
        out_dir = self.root / "fits" / fit_id
        try:
            manifest = fit_layers({"S": body_path},
                                  [{"slot": slot, "path": layer_path}],
                                  out_dir, generation=generation,
                                  fit_id=fit_id)
        except _LIBRARY_ERRORS as e:
            raise Studio2Error(str(e)) from e
        manifest = dict(manifest)
        manifest["fit_dir"] = self._rel(out_dir)
        for entry in manifest.get("entries", []):
            outputs = entry.get("outputs") or {}
            composite = outputs.get("composite") or {}
            if composite.get("filename"):
                composite["file"] = self._rel(
                    out_dir / composite["filename"])
        self._fits[fit_id] = {"manifest": manifest, "dir": out_dir}
        return manifest

    def get_fit(self, fit_id: str) -> dict:
        entry = self._fits.get(fit_id)
        if entry is None:
            raise Studio2Error(f"unknown fit_id: {fit_id}", status=404)
        return entry["manifest"]

    # -- Phase 5: export ----------------------------------------------------

    def export_generation(self, job_id: str, aseprite: bool = False,
                          asset_id=None) -> dict:
        """Export a generation job's outputs as named layers."""
        view = self.get_job(job_id)
        result = view.get("result")
        if not result or not result.get("outputs"):
            raise Studio2Error(f"job {job_id} has no outputs to export",
                               status=409)
        layers = [(f"variation_{i}", self.root / "generated" /
                   o["filename"])
                  for i, o in enumerate(result["outputs"])]
        return self._export(layers=layers, direction_images=None,
                            aseprite=aseprite,
                            asset_id=asset_id or job_id)

    def export_fitting(self, fit_id: str, aseprite: bool = False,
                       asset_id=None) -> dict:
        """Export a fit's per-direction composites (sheet + PNGs)."""
        entry = self._fits.get(fit_id)
        if entry is None:
            raise Studio2Error(f"unknown fit_id: {fit_id}", status=404)
        direction_images = {}
        for e in entry["manifest"].get("entries", []):
            outputs = e.get("outputs") or {}
            composite = outputs.get("composite") or {}
            if e.get("status") == "ok" and composite.get("filename"):
                direction_images[e["direction"]] = (
                    entry["dir"] / composite["filename"])
        if not direction_images:
            raise Studio2Error(
                f"fit {fit_id} has no completed direction composites",
                status=409)
        return self._export(layers=None,
                            direction_images=direction_images,
                            aseprite=aseprite,
                            asset_id=asset_id or fit_id)

    def _export(self, layers, direction_images, aseprite, asset_id) -> dict:
        export_id = "exp_" + uuid.uuid4().hex
        out_dir = self.root / "exports" / export_id
        try:
            manifest = export_assets(
                out_dir,
                direction_images=direction_images,
                layers=layers,
                aseprite_name="export.aseprite" if aseprite else None,
                asset_id=_safe_token(asset_id, "export"))
        except _LIBRARY_ERRORS as e:
            raise Studio2Error(str(e)) from e
        result = {
            "export_id": export_id,
            "export_dir": self._rel(out_dir),
            "manifest": manifest,
        }
        # Web-drive saving (2.0, Han 2026-11-24): exports also land
        # on the configured web drive. Best-effort by design - the
        # report rides along in the result and a drive failure
        # never fails the export itself.
        result["webdrive"] = self.sync_to_webdrive()
        return result

    def sync_to_webdrive(self) -> dict:
        """Mirror this service's whole data root to the web drive.

        Returns the mirror report ({status: disabled|ok|error,
        ...}); never raises. Disabled unless PLUSHY_WEBDRIVE_DIR
        points at a (synced) web-drive folder - see
        studio2.webdrive.
        """
        from .webdrive import sync_service_root

        return sync_service_root(self.root)

    # -- file serving -------------------------------------------------------

    def _rel(self, path) -> str:
        return Path(path).relative_to(self.root).as_posix()

    def resolve_file(self, rel_path: str) -> Path:
        """Resolve a service-relative file path for read-only serving.

        The resolved path must stay inside the service root and
        exist; anything else (absolute paths, .. traversal, missing
        files) is refused. Used by the router's file endpoint so the
        UI can preview references, outputs, composites and exports.
        """
        if not rel_path or Path(rel_path).is_absolute():
            raise Studio2Error("file path must be service-relative",
                               status=404)
        resolved = (self.root / rel_path).resolve()
        if resolved.parent != self.root.resolve() and \
                self.root.resolve() not in resolved.parents:
            raise Studio2Error("file path escapes the studio data root",
                               status=404)
        if not resolved.is_file():
            raise Studio2Error(f"no such file: {rel_path}", status=404)
        return resolved
