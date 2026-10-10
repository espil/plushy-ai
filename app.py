"""
Plushy AI — local private Meshy alternative.

FastAPI server exposing an async image→3D generation queue:

  POST /api/generate        → enqueue job (multipart image OR image_url), returns job_id
  GET  /api/status/{job_id} → job status + progress
  GET  /api/result/{job_id} → download the .GLB file
  DELETE /api/job/{job_id}  → cancel / delete job
  GET  /health              → liveness

Design: the POST handler never runs inference. It stores the upload,
creates a job record, pushes the job_id onto an asyncio.Queue and returns
202 immediately. A pool of background worker coroutines (default 1 — one
GPU) pulls jobs and runs the blocking diffusion pipeline in a thread
executor via PlushyPipeline.generate().

Run locally:
  PLUSHY_MOCK=1 uvicorn app:app --reload --port 8000
Run with GPU (docker):
  docker build -t plushy-ai . && docker run --gpus all -p 8000:8000 plushy-ai
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from pipeline import (GenerationOptions, PlushyPipeline, apply_quality_preset,
                      get_pipeline)

# Opt-in low-VRAM mode for 8GB GPUs (RTX 4060): no-op unless PLUSHY_LOWVRAM=1.
# See lowvram_patch.py for what it changes (fp16 autocast, fewer steps, etc.)
try:
    import lowvram_patch
    lowvram_patch.apply_lowvram()
except Exception as e:
    log.warning("lowvram patch skipped: %s", e)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("plushy.app")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NUM_WORKERS = int(os.getenv("PLUSHY_WORKERS", "1"))  # 1 = one GPU, sequential
MAX_UPLOAD_MB = int(os.getenv("PLUSHY_MAX_UPLOAD_MB", "25"))
JOB_TTL_SEC = int(os.getenv("PLUSHY_JOB_TTL_SEC", "86400"))  # 24h retention


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    job_id: str
    batch_id: Optional[str] = None
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    message: str = "queued"
    image_path: Optional[Path] = None
    options: GenerationOptions = field(default_factory=GenerationOptions)
    result_path: Optional[Path] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    vertex_count: int = 0
    face_count: int = 0


jobs: dict[str, Job] = {}
job_queue: asyncio.Queue[str] = asyncio.Queue()
batches: dict[str, dict] = {}  # batch_id -> {batch_id, job_ids, created_at, zip_path}
_workers: list[asyncio.Task] = []
_pipeline: Optional[PlushyPipeline] = None


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class GenerateResponse(BaseModel):
    job_id: str
    status: JobStatus
    poll_url: str = Field(description="GET this URL for status")
    message: str = "job queued"


class StatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: float
    message: str
    result_url: Optional[str] = None
    error: Optional[str] = None
    elapsed_sec: Optional[float] = None
    vertex_count: int = 0
    face_count: int = 0


class BatchEnqueueResponse(BaseModel):
    batch_id: str
    job_ids: list[str]
    total: int
    accepted: int
    rejected: int
    status_url: str = Field(description="GET this URL for aggregate batch status")


class BatchStatusResponse(BaseModel):
    batch_id: str
    total: int
    queued: int
    processing: int
    completed: int
    failed: int
    cancelled: int
    progress: float
    download_url: Optional[str] = None
    jobs: list[StatusResponse]


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Plushy AI", version="0.2.0",
              description="Local, private image→3D (GLB) generation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _job_to_response(job: Job) -> StatusResponse:
    elapsed = None
    if job.started_at:
        end = job.finished_at or time.time()
        elapsed = round(end - job.started_at, 2)
    return StatusResponse(
        job_id=job.job_id,
        status=job.status,
        progress=round(job.progress, 3),
        message=job.message,
        result_url=f"/api/result/{job.job_id}" if job.status == JobStatus.COMPLETED else None,
        error=job.error,
        elapsed_sec=elapsed,
        vertex_count=job.vertex_count,
        face_count=job.face_count,
    )


async def _download_image_url(url: str, dest: Path):
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if "image" not in ctype and len(r.content) < 100:
            raise ValueError(f"URL did not return an image (content-type={ctype})")
        dest.write_bytes(r.content)


def _validate_image_file(path: Path):
    """Ensure a saved file decodes as an image. Raises HTTPException."""
    from PIL import Image as PILImage
    try:
        with PILImage.open(path) as im:
            im.verify()
    except Exception:
        path.unlink(missing_ok=True)
        raise HTTPException(400, f"not a valid image: {path.name}")


async def _store_image_upload(image: UploadFile, job_id: str) -> Path:
    """Save an uploaded image to disk with size cap + validity check."""
    if image.content_type and not image.content_type.startswith("image/"):
        raise HTTPException(400, f"not an image: {image.content_type}")
    dest = UPLOAD_DIR / f"{job_id}.input"
    try:
        size = 0
        with dest.open("wb") as f:
            while chunk := await image.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_MB * 1024 * 1024:
                    raise HTTPException(413, f"image exceeds {MAX_UPLOAD_MB}MB")
                f.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    _validate_image_file(dest)
    return dest


def _make_options(seed: int, num_inference_steps: int, guidance_scale: float,
                  octree_resolution: int, simplify_ratio: float,
                  with_texture: bool, remove_background: bool,
                  quality: Optional[str] = None) -> GenerationOptions:
    opts = GenerationOptions(
        seed=seed,
        num_inference_steps=max(1, min(num_inference_steps, 100)),
        guidance_scale=guidance_scale,
        octree_resolution=octree_resolution,
        simplify_ratio=max(0.05, min(simplify_ratio, 1.0)),
        with_texture=with_texture,
        remove_background=remove_background,
    )
    if quality:
        # Swagger UI submits its literal placeholder "string" when the field
        # is left untouched — treat that (and blanks) as "not provided".
        if quality.strip().lower() in ("", "string"):
            quality = None
    if quality:
        # named preset overrides the steps/octree/simplify knobs;
        # an invalid value is a 400, never a 500
        try:
            apply_quality_preset(opts, quality)
        except ValueError as e:
            raise HTTPException(400, str(e))
    return opts


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------

async def _worker(worker_id: int):
    global _pipeline
    log.info("worker-%d started", worker_id)
    while True:
        job_id = await job_queue.get()
        job = jobs.get(job_id)
        if job is None or job.status == JobStatus.CANCELLED:
            job_queue.task_done()
            continue
        job.status = JobStatus.PROCESSING
        job.started_at = time.time()
        job.message = "processing"
        log.info("worker-%d picked up job %s", worker_id, job_id)

        def _progress(p: float, msg: str):
            job.progress = p
            job.message = msg

        try:
            result = await _pipeline.generate(
                job.image_path, job.options, job_id=job_id, progress=_progress)
            job.result_path = result.glb_path
            job.vertex_count = result.vertex_count
            job.face_count = result.face_count
            job.status = JobStatus.COMPLETED
            job.progress = 1.0
            job.message = f"done in {result.elapsed_sec:.1f}s"
            log.info("job %s completed → %s", job_id, result.glb_path)
        except asyncio.CancelledError:
            job.status = JobStatus.CANCELLED
            job.message = "cancelled"
            raise
        except Exception as e:
            log.exception("job %s failed", job_id)
            job.status = JobStatus.FAILED
            job.error = f"{type(e).__name__}: {e}"
            job.message = "failed"
        finally:
            job.finished_at = time.time()
            # input upload no longer needed — keep it small
            try:
                if job.image_path and job.image_path.exists():
                    job.image_path.unlink()
            except OSError:
                pass
            job_queue.task_done()


async def _janitor():
    """Delete jobs + files older than JOB_TTL_SEC."""
    while True:
        await asyncio.sleep(3600)
        now = time.time()
        for job_id, job in list(jobs.items()):
            if now - job.created_at > JOB_TTL_SEC:
                for p in (job.result_path, job.image_path):
                    try:
                        if p and p.exists():
                            p.unlink()
                    except OSError:
                        pass
                jobs.pop(job_id, None)
                log.info("expired job %s cleaned up", job_id)
        for batch_id, batch in list(batches.items()):
            if now - batch["created_at"] > JOB_TTL_SEC:
                zp = batch.get("zip_path")
                try:
                    if zp and zp.exists():
                        zp.unlink()
                except OSError:
                    pass
                batches.pop(batch_id, None)
                log.info("expired batch %s cleaned up", batch_id)


@app.on_event("startup")
async def _startup():
    global _pipeline
    _pipeline = get_pipeline(output_dir=OUTPUT_DIR)
    # Warm up model weights in a thread so boot isn't blocked forever;
    # first real job also triggers lazy load if warmup is still going.
    asyncio.get_running_loop().run_in_executor(None, _pipeline.warmup)
    for i in range(max(1, NUM_WORKERS)):
        _workers.append(asyncio.create_task(_worker(i)))
    asyncio.create_task(_janitor())
    log.info("Plushy AI ready — %d worker(s), uploads=%s outputs=%s",
             NUM_WORKERS, UPLOAD_DIR, OUTPUT_DIR)


@app.on_event("shutdown")
async def _shutdown():
    for w in _workers:
        w.cancel()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "backend": os.getenv("PLUSHY_BACKEND", "trellis"),
        "mock": os.getenv("PLUSHY_MOCK", "0") == "1",
        "workers": NUM_WORKERS,
        "queued": job_queue.qsize(),
        "jobs": len(jobs),
    }


@app.post("/api/generate", status_code=202, response_model=GenerateResponse)
async def generate(
    image: Optional[UploadFile] = File(None, description="Input image (png/jpg/webp)"),
    image_url: Optional[str] = Form(None, description="…or a URL to an image"),
    seed: int = Form(0),
    num_inference_steps: int = Form(25),
    guidance_scale: float = Form(7.5),
    octree_resolution: int = Form(256),
    simplify_ratio: float = Form(0.9),
    with_texture: bool = Form(True),
    remove_background: bool = Form(True),
    quality: Optional[str] = Form(None, description="quality preset: draft|balanced|detailed (overrides steps/octree/simplify)"),
):
    """Enqueue an image→3D job. Returns immediately with a job_id (202)."""
    if image is None and not image_url:
        raise HTTPException(400, "provide either `image` (upload) or `image_url`")

    job_id = uuid.uuid4().hex[:12]

    if image is not None:
        dest = await _store_image_upload(image, job_id)
    else:
        dest = UPLOAD_DIR / f"{job_id}.input"
        try:
            await _download_image_url(image_url, dest)
        except Exception as e:
            dest.unlink(missing_ok=True)
            raise HTTPException(400, f"could not fetch image_url: {e}")
        _validate_image_file(dest)

    opts = _make_options(seed, num_inference_steps, guidance_scale,
                         octree_resolution, simplify_ratio,
                         with_texture, remove_background, quality)
    jobs[job_id] = Job(job_id=job_id, image_path=dest, options=opts)
    await job_queue.put(job_id)
    log.info("enqueued job %s (queue depth %d)", job_id, job_queue.qsize())
    return GenerateResponse(
        job_id=job_id,
        status=JobStatus.QUEUED,
        poll_url=f"/api/status/{job_id}",
        message=f"job queued at position {job_queue.qsize()}",
    )


@app.post("/api/batch", status_code=202, response_model=BatchEnqueueResponse)
async def batch_generate(
    images: list[UploadFile] = File(..., description="One or more images (max 100)"),
    seed: int = Form(0),
    num_inference_steps: int = Form(25),
    guidance_scale: float = Form(7.5),
    octree_resolution: int = Form(256),
    simplify_ratio: float = Form(0.9),
    with_texture: bool = Form(True),
    remove_background: bool = Form(True),
    quality: Optional[str] = Form(None, description="quality preset: draft|balanced|detailed (overrides steps/octree/simplify)"),
):
    """Enqueue many image→3D jobs at once. Returns a batch_id + per-image job_ids (202).

    Each image is validated independently: bad files are recorded as failed
    jobs instead of rejecting the whole batch. Per-image seed = seed + index.
    """
    if not images:
        raise HTTPException(400, "no images provided")
    if len(images) > 100:
        raise HTTPException(400, "max 100 images per batch")

    batch_id = uuid.uuid4().hex[:12]
    job_ids: list[str] = []
    accepted = 0

    for i, image in enumerate(images):
        job_id = f"{batch_id}-{i:03d}"
        opts = _make_options(seed + i, num_inference_steps, guidance_scale,
                             octree_resolution, simplify_ratio,
                             with_texture, remove_background, quality)
        try:
            dest = await _store_image_upload(image, job_id)
        except HTTPException as e:
            jobs[job_id] = Job(job_id=job_id, batch_id=batch_id,
                               status=JobStatus.FAILED, message="failed",
                               error=str(e.detail), options=opts)
            job_ids.append(job_id)
            continue
        jobs[job_id] = Job(job_id=job_id, batch_id=batch_id,
                           image_path=dest, options=opts)
        await job_queue.put(job_id)
        job_ids.append(job_id)
        accepted += 1

    batches[batch_id] = {
        "batch_id": batch_id,
        "job_ids": job_ids,
        "created_at": time.time(),
        "zip_path": None,
    }
    log.info("enqueued batch %s: %d accepted, %d rejected",
             batch_id, accepted, len(job_ids) - accepted)
    return BatchEnqueueResponse(
        batch_id=batch_id,
        job_ids=job_ids,
        total=len(job_ids),
        accepted=accepted,
        rejected=len(job_ids) - accepted,
        status_url=f"/api/batch/{batch_id}",
    )


@app.get("/api/batch/{batch_id}", response_model=BatchStatusResponse)
async def batch_status(batch_id: str):
    batch = batches.get(batch_id)
    if batch is None:
        raise HTTPException(404, "unknown batch_id")
    counts = {s: 0 for s in JobStatus}
    job_responses = []
    for jid in batch["job_ids"]:
        job = jobs.get(jid)
        if job is None:
            continue
        counts[job.status] += 1
        job_responses.append(_job_to_response(job))
    total = len(batch["job_ids"])
    done = counts[JobStatus.COMPLETED] + counts[JobStatus.FAILED] + counts[JobStatus.CANCELLED]
    return BatchStatusResponse(
        batch_id=batch_id,
        total=total,
        queued=counts[JobStatus.QUEUED],
        processing=counts[JobStatus.PROCESSING],
        completed=counts[JobStatus.COMPLETED],
        failed=counts[JobStatus.FAILED],
        cancelled=counts[JobStatus.CANCELLED],
        progress=round(done / total, 3) if total else 0.0,
        download_url=f"/api/batch/{batch_id}/download" if counts[JobStatus.COMPLETED] else None,
        jobs=job_responses,
    )


@app.get("/api/batch/{batch_id}/download")
async def batch_download(batch_id: str):
    """Download all completed GLBs in the batch as a single .zip."""
    import zipfile

    batch = batches.get(batch_id)
    if batch is None:
        raise HTTPException(404, "unknown batch_id")
    done = [jobs[jid] for jid in batch["job_ids"]
            if jid in jobs and jobs[jid].status == JobStatus.COMPLETED
            and jobs[jid].result_path and jobs[jid].result_path.exists()]
    if not done:
        raise HTTPException(409, "no completed GLBs in this batch yet")
    zip_path = OUTPUT_DIR / f"batch-{batch_id}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for job in done:
            zf.write(job.result_path, arcname=f"{job.job_id}.glb")
    batch["zip_path"] = zip_path
    log.info("batch %s zip built: %d GLBs → %s", batch_id, len(done), zip_path)
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"plushy-batch-{batch_id}.zip",
    )


@app.get("/api/status/{job_id}", response_model=StatusResponse)
async def status(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job_id")
    return _job_to_response(job)


@app.get("/api/result/{job_id}")
async def result(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job_id")
    if job.status != JobStatus.COMPLETED or not job.result_path:
        raise HTTPException(409, f"job not ready (status={job.status.value})")
    if not job.result_path.exists():
        raise HTTPException(410, "result file expired")
    return FileResponse(
        job.result_path,
        media_type="model/gltf-binary",
        filename=f"plushy-{job_id}.glb",
    )


@app.delete("/api/job/{job_id}")
async def delete_job(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job_id")
    job.status = JobStatus.CANCELLED
    job.message = "cancelled by user"
    for p in (job.result_path, job.image_path):
        try:
            if p and p.exists():
                p.unlink()
        except OSError:
            pass
    jobs.pop(job_id, None)
    return JSONResponse({"job_id": job_id, "deleted": True})


@app.get("/studio")
async def studio():
    """Decent web UI: upload → generate → 3D preview → download."""
    html = BASE_DIR / "static" / "studio.html"
    if not html.exists():
        raise HTTPException(404, "studio UI not installed")
    return FileResponse(html, media_type="text/html")


@app.get("/")
async def index():
    return {
        "name": "Plushy AI",
        "studio": "/studio",
        "docs": "/docs",
        "generate": "POST /api/generate (multipart: image | image_url)",
        "batch": "POST /api/batch (multipart: images[] — up to 100)",
    }
