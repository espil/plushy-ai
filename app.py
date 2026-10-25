"""
Plushy AI - local sprite generator (sprite-only build).

Text prompt -> SDXL-Turbo -> background removal -> transparent PNG,
ready as billboard sprites in a game engine. No cloud, your GPU.

Endpoints:
  POST /api/sprite        → 202 + job_id (JSON: prompt, seed, size, steps)
  POST /api/img2img       → 202 + job_id (multipart: image + prompt + strength)
  POST /api/model3d       → 202 + job_id (multipart: image) -> textured GLB
  GET  /api/status/{job_id}
  GET  /api/result/{job_id} → download the transparent .PNG
  GET  /api/outputs          → list sprites already on disk (newest first)
  GET  /api/outputs/{name}   → download one existing output PNG
  DELETE /api/job/{job_id}  → cancel / delete job
  GET  /health              → liveness
  GET  /studio              → web UI
  GET  /                    → index

Design: the POST handler never runs inference. It creates a job record,
pushes the job_id onto an asyncio.Queue and returns 202 immediately.
Background worker coroutines pull jobs and run the diffusion pipeline in a
thread executor so the event loop never blocks.

Run locally (mock placeholders, no GPU):
  PLUSHY_MOCK=1 python -m uvicorn app:app --host 0.0.0.0 --port 8000
Run with GPU (docker):
  docker build -t plushy-ai . && docker run --gpus all -p 8000:8000 plushy-ai

Outputs: PLUSHY_OUTPUT_DIR wins when set. Otherwise outputs stay in the
repo's local outputs folder.
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


def _resolve_output_dir() -> Path:
    """Where generated PNGs land.

    PLUSHY_OUTPUT_DIR is the explicit override (the Docker launcher points
    it at the mounted /app/outputs). Otherwise outputs stay in the repo's
    local outputs folder.
    """
    configured = os.getenv("PLUSHY_OUTPUT_DIR")
    if configured:
        return Path(configured).expanduser()
    return BASE_DIR / "outputs"


OUTPUT_DIR = _resolve_output_dir()
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
    mode: str = "t2i"                      # "t2i" | "i2i" | "m3d"
    kind: str = "sprite"                   # "sprite" | "model3d"
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
_model3d_pipeline = None


def _get_sprite_pipeline():
    global _sprite_pipeline
    if _sprite_pipeline is None:
        from pipeline_sprite import SpritePipeline
        _sprite_pipeline = SpritePipeline()
    return _sprite_pipeline


def _get_model3d_pipeline():
    global _model3d_pipeline
    if _model3d_pipeline is None:
        from pipeline_3d import Model3DPipeline
        _model3d_pipeline = Model3DPipeline()
    return _model3d_pipeline


def _model3d_health() -> dict:
    try:
        from pipeline_3d import SF3D_MODEL, engine_installed
        return {"engine": "sf3d", "model": SF3D_MODEL, "mock": MOCK,
                "installed": engine_installed()}
    except Exception as e:
        return {"engine": "sf3d", "installed": False,
                "error": f"{type(e).__name__}: {e}"}


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
        log.info("worker-%d picked up job %s (kind=%s)", worker_id, job_id, job.kind)

        def _progress(p: float, msg: str):
            job.progress = p
            job.message = msg

        if job.kind == "model3d":
            await _run_model3d_job(job, _progress)
            job_queue.task_done()
            continue

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


async def _run_model3d_job(job: Job, progress):
    """Execute one image-to-3D job (SF3D). Mirrors the sprite worker's
    error handling; never raises except CancelledError."""
    try:
        from pipeline_3d import Model3DOptions
        pipe = _get_model3d_pipeline()
        opts = Model3DOptions(texture_resolution=job.size)
        dest = OUTPUT_DIR / f"{job.job_id}.model3d.glb"
        t0 = time.time()
        loop = asyncio.get_running_loop()
        actual, stats = await loop.run_in_executor(
            None, pipe.image_to_glb, job.init_image, dest, opts, progress)
        job.result_path = actual
        job.status = JobStatus.COMPLETED
        job.progress = 1.0
        label = "MOCK placeholder (not a real model)" if stats.get("mock") else "model"
        job.message = f"{label} done in {time.time() - t0:.1f}s"
        log.info("model3d job %s completed → %s", job.job_id, actual)
    except asyncio.CancelledError:
        job.status = JobStatus.CANCELLED
        job.message = "cancelled"
        raise
    except Exception as e:
        log.exception("model3d job %s failed", job.job_id)
        job.status = JobStatus.FAILED
        job.error = f"{type(e).__name__}: {e}"
        job.message = "failed"
    finally:
        job.finished_at = time.time()


async def _janitor():
    """Expire job records older than JOB_TTL_SEC.

    Result PNGs are kept: the output folder doubles as the local archive
    on Han's PC, and /api/outputs lists what is on disk. Only
    the in-memory record and any uploaded img2img source are removed.
    Manual DELETE /api/job/{job_id} still removes that job's result.
    """
    while True:
        await asyncio.sleep(3600)
        now = time.time()
        for job_id, job in list(jobs.items()):
            if now - job.created_at > JOB_TTL_SEC:
                try:
                    if job.init_image and job.init_image.exists():
                        job.init_image.unlink()
                except OSError:
                    pass
                jobs.pop(job_id, None)
                log.info("expired job %s cleaned up (result kept on disk)", job_id)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Plushy AI", description="Local text-to-sprite generator")


@app.on_event("startup")
async def _startup():
    for i in range(max(1, NUM_WORKERS)):
        _workers.append(asyncio.create_task(_worker(i)))
    asyncio.create_task(_janitor())
    log.info("Plushy AI ready - %d worker(s), outputs=%s, mock=%s",
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
        "output_dir": str(OUTPUT_DIR),
        "model3d": _model3d_health(),
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


@app.post("/api/model3d", status_code=202, response_model=GenerateResponse)
async def create_model3d(
    image: UploadFile = File(...),
    texture_resolution: int = Form(1024),
):
    """Upload one image -> textured 3D model (GLB), generated locally by SF3D.

    Mock mode (PLUSHY_MOCK=1) returns a clearly stamped *_MOCK.glb
    placeholder instead - the job message says so.
    """
    job_id = uuid.uuid4().hex[:12]
    upload_dir = OUTPUT_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    init_path = upload_dir / f"{job_id}_src.png"
    data = await image.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "image too large (max 20MB)")
    init_path.write_bytes(data)
    tex = texture_resolution if texture_resolution in (512, 1024, 2048) else 1024
    jobs[job_id] = Job(
        job_id=job_id,
        prompt="(image-to-3d)",
        size=tex,
        mode="m3d",
        kind="model3d",
        init_image=init_path,
    )
    await job_queue.put(job_id)
    log.info("enqueued model3d job %s (queue depth %d)", job_id, job_queue.qsize())
    return GenerateResponse(job_id=job_id, status=JobStatus.QUEUED,
                            poll_url=f"/api/status/{job_id}")


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
    if job.result_path.suffix == ".glb":
        return FileResponse(
            job.result_path,
            media_type="model/gltf-binary",
            filename=f"plushy-model-{job_id}.glb",
        )
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


@app.get("/api/outputs")
async def list_outputs():
    """List every sprite already on disk (newest first).

    The Studio gallery is in-browser memory only, so without this a
    refresh - or opening /studio from a second PC - shows nothing even
    though the PNGs are sitting in outputs/. This is what makes past
    generations viewable from another machine on the LAN.
    """
    items = []
    files = sorted(list(OUTPUT_DIR.glob("*.png")) + list(OUTPUT_DIR.glob("*.glb")),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    for p in files:
        st = p.stat()
        items.append({
            "name": p.name,
            "url": f"/api/outputs/{p.name}",
            "kind": "glb" if p.suffix == ".glb" else "png",
            "size_bytes": st.st_size,
            "mtime": int(st.st_mtime),
        })
    return {"count": len(items), "outputs": items}


@app.get("/api/outputs/{name}")
async def get_output(name: str):
    # Path(name).name strips any directory part - no traversal out of outputs/.
    safe = Path(name).name
    if safe != name or not (safe.endswith(".png") or safe.endswith(".glb")):
        raise HTTPException(400, "bad file name")
    path = OUTPUT_DIR / safe
    if not path.exists():
        raise HTTPException(404, "no such output")
    media = "model/gltf-binary" if safe.endswith(".glb") else "image/png"
    return FileResponse(path, media_type=media, filename=safe)


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
        "model3d": "POST /api/model3d (multipart: image, texture_resolution) -> textured GLB",
    }
