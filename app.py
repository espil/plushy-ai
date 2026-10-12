"""
Plushy AI — local sprite generator (sprite-only build).

Text prompt -> SDXL-Turbo -> background removal -> transparent PNG,
ready as billboard sprites in a game engine. No cloud, your GPU.

Endpoints:
  POST /api/sprite        → 202 + job_id (JSON: prompt, seed, size, steps)
  POST /api/img2img       → 202 + job_id (multipart: image + prompt + strength)
  GET  /api/status/{job_id}
  GET  /api/result/{job_id} → download the transparent .PNG
  DELETE /api/job/{job_id}  → cancel / delete job
  GET  /health              → liveness
  GET  /studio              → web UI
  GET  /                    → index

Design: the POST handler never runs inference. It creates a job record,
pushes the job_id onto an asyncio.Queue and returns 202 immediately.
Background worker coroutines pull jobs and run the diffusion pipeline in a
thread executor so the event loop never blocks.

Run locally (mock placeholders, no GPU):
  PLUSHY_MOCK=1 python -m uvicorn app:app --port 8000
Run with GPU (docker):
  docker build -t plushy-ai . && docker run --gpus all -p 8000:8000 plushy-ai
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("plushy")

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NUM_WORKERS = int(os.getenv("PLUSHY_WORKERS", "1"))  # 1 = one GPU, sequential
JOB_TTL_SEC = int(os.getenv("PLUSHY_JOB_TTL_SEC", "86400"))  # 24h retention
MOCK = os.getenv("PLUSHY_MOCK", "0") == "1"


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    job_id: str
    prompt: str
    seed: int = 0
    size: int = 512
    steps: int = 4
    negative_prompt: Optional[str] = None
    style: str = "default"
    mode: str = "t2i"                      # "t2i" | "i2i"
    init_image: Optional[Path] = None      # uploaded base image (i2i)
    strength: float = 0.6                  # img2img strength (i2i)
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    message: str = "queued"
    result_path: Optional[Path] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


jobs: dict[str, Job] = {}
job_queue: asyncio.Queue[str] = asyncio.Queue()
_workers: list[asyncio.Task] = []
_sprite_pipeline = None


def _get_sprite_pipeline():
    global _sprite_pipeline
    if _sprite_pipeline is None:
        from pipeline_sprite import SpritePipeline
        _sprite_pipeline = SpritePipeline()
    return _sprite_pipeline


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


class SpriteRequest(BaseModel):
    prompt: str = Field(description="what to generate, e.g. 'a pine tree'")
    seed: int = 0
    size: int = Field(512, description="square size in px (64-1024)")
    steps: int = Field(4, description="inference steps (SDXL-Turbo: 1-4)")
    negative_prompt: Optional[str] = Field(None, description="overrides the default negative prompt")
    style: str = Field("default", description="art style preset: default | 2.5d | 3d | chibi")


def _job_to_response(job: Job) -> StatusResponse:
    elapsed = None
    if job.started_at:
        end = job.finished_at or time.time()
        elapsed = round(end - job.started_at, 1)
    return StatusResponse(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        message=job.message,
        result_url=f"/api/result/{job.job_id}" if job.status == JobStatus.COMPLETED else None,
        error=job.error,
        elapsed_sec=elapsed,
    )


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------

async def _worker(worker_id: int):
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
        log.info("worker-%d picked up sprite job %s", worker_id, job_id)

        def _progress(p: float, msg: str):
            job.progress = p
            job.message = msg

        try:
            from pipeline_sprite import SpriteOptions
            pipe = _get_sprite_pipeline()
            sopts = SpriteOptions(
                width=job.size, height=job.size,
                seed=job.seed,
                num_inference_steps=job.steps,
                style=job.style,
            )
            if job.negative_prompt:
                sopts.negative_prompt = job.negative_prompt
            dest = OUTPUT_DIR / f"{job_id}.sprite.png"
            t0 = time.time()
            loop = asyncio.get_running_loop()
            if job.mode == "i2i" and job.init_image is not None:
                from PIL import Image
                init = Image.open(job.init_image).convert("RGBA")
                # SDXL wants multiples of 8
                w = max(64, init.width // 8 * 8)
                h = max(64, init.height // 8 * 8)
                if (w, h) != init.size:
                    init = init.resize((w, h))
                await loop.run_in_executor(
                    None, pipe.img2img_to_file,
                    job.prompt, init, dest, job.strength, sopts, _progress)
            else:
                await loop.run_in_executor(
                    None, pipe.generate_to_file,
                    job.prompt, dest, sopts, _progress)
            job.result_path = dest
            job.status = JobStatus.COMPLETED
            job.progress = 1.0
            job.message = f"done in {time.time() - t0:.1f}s"
            log.info("sprite job %s completed → %s", job_id, dest)
        except asyncio.CancelledError:
            job.status = JobStatus.CANCELLED
            job.message = "cancelled"
            raise
        except Exception as e:
            log.exception("sprite job %s failed", job_id)
            job.status = JobStatus.FAILED
            job.error = f"{type(e).__name__}: {e}"
            job.message = "failed"
        finally:
            job.finished_at = time.time()
            job_queue.task_done()


async def _janitor():
    """Delete jobs + files older than JOB_TTL_SEC."""
    while True:
        await asyncio.sleep(3600)
        now = time.time()
        for job_id, job in list(jobs.items()):
            if now - job.created_at > JOB_TTL_SEC:
                try:
                    if job.result_path and job.result_path.exists():
                        job.result_path.unlink()
                except OSError:
                    pass
                jobs.pop(job_id, None)
                log.info("expired job %s cleaned up", job_id)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Plushy AI", description="Local text-to-sprite generator")


@app.on_event("startup")
async def _startup():
    for i in range(max(1, NUM_WORKERS)):
        _workers.append(asyncio.create_task(_worker(i)))
    asyncio.create_task(_janitor())
    log.info("Plushy AI ready — %d worker(s), outputs=%s, mock=%s",
             NUM_WORKERS, OUTPUT_DIR, MOCK)


@app.on_event("shutdown")
async def _shutdown():
    for w in _workers:
        w.cancel()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mode": "sprite",
        "mock": MOCK,
        "workers": NUM_WORKERS,
        "queued": job_queue.qsize(),
        "jobs": len(jobs),
    }


@app.post("/api/sprite", status_code=202, response_model=GenerateResponse)
async def sprite(req: SpriteRequest):
    """Enqueue a text→sprite job (transparent PNG). Returns 202 + job_id."""
    prompt = (req.prompt or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt is required")
    if len(prompt) > 500:
        raise HTTPException(400, "prompt too long (max 500 chars)")
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = Job(
        job_id=job_id,
        prompt=prompt,
        seed=req.seed,
        size=max(64, min(req.size, 1024)),
        steps=max(1, min(req.steps, 12)),
        negative_prompt=req.negative_prompt,
        style=req.style if req.style in ("default", "2.5d", "3d", "chibi") else "default",
    )
    await job_queue.put(job_id)
    log.info("enqueued sprite job %s (queue depth %d)", job_id, job_queue.qsize())
    return GenerateResponse(
        job_id=job_id,
        status=JobStatus.QUEUED,
        poll_url=f"/api/status/{job_id}",
        message=f"sprite job queued at position {job_queue.qsize()}",
    )


@app.post("/api/img2img", status_code=202, response_model=GenerateResponse)
async def create_img2img(
    image: UploadFile = File(...),
    prompt: str = Form(...),
    seed: int = Form(0),
    steps: int = Form(6),
    strength: float = Form(0.6),
    style: str = Form("default"),
    negative_prompt: Optional[str] = Form(None),
):
    """Upload a base image + prompt -> img2img (e.g. dress a blank body)."""
    job_id = uuid.uuid4().hex[:12]
    upload_dir = OUTPUT_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    init_path = upload_dir / f"{job_id}_init.png"
    data = await image.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "image too large (max 20MB)")
    init_path.write_bytes(data)
    jobs[job_id] = Job(
        job_id=job_id,
        prompt=prompt.strip(),
        seed=seed,
        size=512,
        steps=max(1, min(steps, 12)),
        negative_prompt=negative_prompt,
        style=style if style in ("default", "2.5d", "3d", "chibi") else "default",
        mode="i2i",
        init_image=init_path,
        strength=max(0.1, min(strength, 1.0)),
    )
    await job_queue.put(job_id)
    return GenerateResponse(job_id=job_id, status=JobStatus.QUEUED, poll_url=f"/api/status/{job_id}")


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
        media_type="image/png",
        filename=f"plushy-sprite-{job_id}.png",
    )


@app.delete("/api/job/{job_id}")
async def delete_job(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job_id")
    job.status = JobStatus.CANCELLED
    job.message = "cancelled by user"
    try:
        if job.result_path and job.result_path.exists():
            job.result_path.unlink()
    except OSError:
        pass
    jobs.pop(job_id, None)
    return JSONResponse({"job_id": job_id, "deleted": True})


@app.get("/studio")
async def studio():
    """Web UI: prompt → sprite → preview → download."""
    html = BASE_DIR / "static" / "studio.html"
    if not html.exists():
        raise HTTPException(404, "studio UI not installed")
    return FileResponse(html, media_type="text/html")


@app.get("/")
async def index():
    return {
        "name": "Plushy AI",
        "mode": "sprite",
        "studio": "/studio",
        "docs": "/docs",
        "sprite": "POST /api/sprite (JSON: prompt, seed, size, steps) -> transparent PNG",
    }
