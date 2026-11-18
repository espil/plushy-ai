"""Thin FastAPI router for the Plushy-AI 2.0 Studio (Phase 6).

This module is the ONLY Phase 6 module that requires FastAPI, and
it is imported only when actually serving (the service layer and
the tests never import it). It is a pure adapter: every endpoint
delegates to `studio2.service.Studio2Service` and translates
Studio2Error into an HTTP status with a plain-text detail. The 1.0
endpoints (/api/sprite, /api/status/{job_id}, /api/result/{job_id},
...) are not touched, moved or shadowed.

Endpoints (the prompt's proposed 2.0 API, section 5):
  POST /api/assets/analyze        image/Aseprite analysis (Phase 1)
  GET  /api/assets/{asset_id}     stored asset-standard record
  POST /api/reference/analyze     validated reference upload (Phase 2)
  POST /api/masks                 mask save / suggestion (Phase 2)
  POST /api/assets/generate       generation job, 202 (Phase 3)
  GET  /api/jobs/{job_id}         job status (registry shape)
  POST /api/paperdoll/compose     paper-doll fit preview (Phase 4)
  POST /api/export                PNG / sheet / Aseprite export (Phase 5)

Support endpoints the 9-screen page needs around those:
  GET  /api/studio2/bootstrap     categories + style profiles
  GET  /api/jobs                  job history (newest first)
  DELETE /api/jobs/{job_id}       cancel a queued job (mirrors the
                                  1.0 DELETE /api/job/{job_id} role)
  POST /api/compare               generated vs baseline facts
  GET  /api/studio2/files?path=   read-only preview/download of
                                  service files (root-confined)

Run it via the standalone entrypoint `studio2_server.py`, which
mounts this router on the unmodified 1.0 app.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, \
    HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from .service import Studio2Error, Studio2Service

BASE_DIR = Path(__file__).resolve().parent.parent

_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".json": "application/json",
    ".aseprite": "application/octet-stream",
    ".ase": "application/octet-stream",
}


def default_service() -> Studio2Service:
    """The serving service instance (root from PLUSHY_STUDIO2_DIR)."""
    root = os.getenv("PLUSHY_STUDIO2_DIR") or str(BASE_DIR / "studio2_data")
    return Studio2Service(root)


def _guard(fn):
    """Translate Studio2Error into a plain-text HTTPException."""
    try:
        return fn()
    except Studio2Error as e:
        raise HTTPException(e.status, str(e)) from e


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"request body is not valid JSON: {e}")
    if not isinstance(body, dict):
        raise HTTPException(400, "request body must be a JSON object")
    return body


def create_router(service: Studio2Service | None = None) -> APIRouter:
    """Build the 2.0 router over `service` (a fresh one if omitted)."""
    svc = service or default_service()
    router = APIRouter()

    @router.get("/api/studio2/bootstrap")
    async def bootstrap():
        return svc.bootstrap()

    # -- Phase 1: assets ------------------------------------------------

    @router.post("/api/assets/analyze")
    async def analyze_asset(file: UploadFile = File(...)):
        data = await file.read()
        return _guard(lambda: svc.analyze_asset(data, file.filename or ""))

    @router.get("/api/assets/{asset_id}")
    async def get_asset(asset_id: str):
        return _guard(lambda: svc.get_asset(asset_id))

    # -- Phase 2: references + masks --------------------------------------

    @router.post("/api/reference/analyze")
    async def analyze_reference(file: UploadFile = File(...),
                                category: str | None = Form(None)):
        data = await file.read()
        return _guard(lambda: svc.analyze_reference_upload(
            data, file.filename or "", category=category))

    @router.post("/api/masks")
    async def save_mask(request: Request):
        body = await _json_body(request)
        if body.get("suggest_only"):
            return _guard(lambda: svc.suggest_mask(body.get("reference_id")))
        return _guard(lambda: svc.save_mask(
            body.get("reference_id"),
            rectangles=body.get("rectangles"),
            base=body.get("base", "empty"),
            confirmed=bool(body.get("confirmed", False)),
            category=body.get("category")))

    # -- Phase 3: generation jobs ------------------------------------------

    @router.post("/api/assets/generate", status_code=202)
    async def generate(request: Request,
                       background: BackgroundTasks):
        body = await _json_body(request)
        view = _guard(lambda: svc.create_generation_job(body))
        background.add_task(svc.run_generation_job, view["job_id"])
        return view

    @router.get("/api/jobs")
    async def list_jobs():
        return {"count": len(svc.list_jobs()), "jobs": svc.list_jobs()}

    @router.get("/api/jobs/{job_id}")
    async def get_job(job_id: str):
        return _guard(lambda: svc.get_job(job_id))

    @router.delete("/api/jobs/{job_id}")
    async def cancel_job(job_id: str):
        return _guard(lambda: svc.cancel_job(job_id))

    @router.post("/api/compare")
    async def compare(request: Request):
        body = await _json_body(request)
        return _guard(lambda: svc.compare(
            body.get("job_id"),
            baseline_reference_id=body.get("baseline_reference_id"),
            output_filename=body.get("output_filename")))

    # -- Phase 4: paper doll -------------------------------------------------

    @router.post("/api/paperdoll/compose")
    async def compose(request: Request):
        body = await _json_body(request)
        return _guard(lambda: svc.compose_paperdoll(
            body.get("body"), body.get("layer"), body.get("slot")))

    # -- Phase 5: export -------------------------------------------------------

    @router.post("/api/export")
    async def export(request: Request):
        body = await _json_body(request)
        source = body.get("source_type", "generation")
        if source == "generation":
            return _guard(lambda: svc.export_generation(
                body.get("job_id"),
                aseprite=bool(body.get("aseprite", False)),
                asset_id=body.get("asset_id")))
        if source == "fitting":
            return _guard(lambda: svc.export_fitting(
                body.get("fit_id"),
                aseprite=bool(body.get("aseprite", False)),
                asset_id=body.get("asset_id")))
        raise HTTPException(
            400, f"source_type must be 'generation' or 'fitting', "
                 f"got {source!r}")

    # -- file previews ----------------------------------------------------------

    @router.get("/api/studio2/files")
    async def get_file(path: str):
        resolved = _guard(lambda: svc.resolve_file(path))
        media = _MEDIA_TYPES.get(resolved.suffix.lower(),
                                 "application/octet-stream")
        return FileResponse(resolved, media_type=media,
                            filename=resolved.name)

    return router
