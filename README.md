# 🧸 Plushy AI — local, private Meshy alternative

Two pipelines, one project. No cloud, no per-generation fees, your GPU.

```
image.png ──▶ POST /api/generate ──▶ queue ──▶ TRELLIS / Hunyuan3D ──▶ model.glb   (3D)
"a pine tree" ──▶ POST /api/sprite ──▶ queue ──▶ SDXL-Turbo + rembg ──▶ sprite.png  (2D sprite)
```

- **3D** (`pipeline_3d.py`): image → 3D GLB for characters and hero assets.
- **Sprites** (`pipeline_sprite.py`): text → transparent PNG, ready as billboard
  sprites in a game engine. Seconds per sprite, a fraction of the VRAM.

## Architecture

| Piece | File | Notes |
|---|---|---|
| API + async queue | `app.py` | FastAPI; `POST /api/generate` and `POST /api/sprite` return `202 + job_id` immediately; background workers (default 1, one GPU) run inference in a thread executor so the event loop never blocks |
| 3D pipeline | `pipeline_3d.py` | Image preprocess (rembg → square pad → 512px) → backend diffusion → mesh cleanup (de-dupe, de-float, decimate, normalize) → standard `.GLB` via trimesh |
| Sprite pipeline | `pipeline_sprite.py` | SDXL-Turbo text-to-image → rembg background removal → transparent `.PNG` |
| GPU environment | `Dockerfile` | CUDA 12.1, torch 2.3, TRELLIS from source, diffusers for sprites |

### Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/generate` | multipart `image` **or** form `image_url`; tunable `seed`, `num_inference_steps`, `guidance_scale`, `octree_resolution`, `simplify_ratio`, `with_texture`, `remove_background` → `202 { job_id, poll_url }` |
| `GET` | `/api/status/{job_id}` | `{ status, progress, message, result_url, elapsed_sec, vertex_count, face_count }` |
| `GET` | `/api/result/{job_id}` | downloads the `.GLB` (`model/gltf-binary`) |
| `POST` | `/api/batch` | multipart `images` (up to 100); per-image seed = seed+index → `202 { batch_id, job_ids }` |
| `GET` | `/api/batch/{batch_id}` | aggregate counts + per-job statuses |
| `GET` | `/api/batch/{batch_id}/download` | all completed GLBs as one `.zip` |
| `DELETE` | `/api/job/{job_id}` | cancel + delete |
| `POST` | `/api/sprite` | JSON `prompt`, `seed`, `size`, `steps` → `202 { job_id, poll_url }`; result is a transparent `.PNG` (`image/png`) |
| `GET` | `/health` | liveness, backend, queue depth |

## Sprite mode — text → transparent PNG

For billboard sprites (trees, props, street furniture). Much faster and
lighter than 3D — seconds per sprite on an 8GB GPU.

```bash
# single sprite
python sprites.py --prompt "a pine tree" --output ./my_sprites

# batch from a prompts file (one per line, # = comment)
python sprites.py --prompts prompts.txt --output ./my_sprites --seeds 3 --size 256
```

Or via the API / studio GUI (`/studio` → Sprite tab).

## Batch mode — many images → many GLBs

Two ways, same engine. **Use your own original concept art.**

### CLI (simplest — ideal for local runs on your PC)

```bash
python batch.py --input ./my_art --output ./my_glbs
```

- Every `png/jpg/webp` in `./my_art` becomes `<name>.glb` in `./my_glbs`
- `manifest.json` records per-file status, timing, seed, verts/faces
- `--skip-existing` resumes an interrupted run; `--seed 42 --steps 20` tune generation
- `--mock` for a no-GPU dry run; `-r` scans subfolders too

```bash
python batch.py --input ./my_art --output ./my_glbs --seed 42 --skip-existing
```

### API

```bash
# enqueue up to 100 images in one call → 202 { batch_id, job_ids }
curl -X POST http://localhost:8000/api/batch \
  -F "images=@hat1.png" -F "images=@hat2.png" -F "images=@sword.png"

# aggregate progress
curl http://localhost:8000/api/batch/<batch_id>
# → { total, queued, processing, completed, failed, progress, download_url, jobs: [...] }

# all finished GLBs as one zip
curl -OJ http://localhost:8000/api/batch/<batch_id>/download
```

Bad files don't kill the batch — they're recorded as failed jobs and the
rest continue.

## Quality presets — more detail, still low-poly

`--quality` (CLI) or `quality=` (API) sets three knobs at once:

| preset | steps | octree | simplify | when to use |
|---|---|---|---|---|
| `draft` | 12 | 128 | 0.70 | fast iteration, shape check |
| `balanced` | 25 | 256 | 0.90 | default, good on 8GB |
| `detailed` | 50 | 512 | 0.95 | max detail — needs 12GB+ VRAM, or `PLUSHY_LOWVRAM=1` may still OOM |

```bash
python batch.py --input ./my_art --output ./my_glbs --quality detailed
curl -X POST http://localhost:8000/api/generate -F "image=@a.png" -F "quality=detailed"
```

Explicit `--steps` / `--octree` / `--simplify` override the preset. Notes:

- **Input image matters most.** Clean background (rembg is on by default),
  front-facing, well-lit, single subject. A good photo beats any knob.
- **Low-poly + detail is not a contradiction here:** the mesh is always
  decimated to `simplify_ratio`, so at low face counts almost all perceived
  detail comes from the **texture** — keep `with_texture` on.
- **Seeds are cheap lottery tickets.** Run the same image with 3–5 seeds
  (`--seed 0..4`) and keep the best; quality varies more between seeds than
  between 25 and 50 steps.
- On 8GB, `detailed` + `PLUSHY_LOWVRAM=1` fight each other (low-VRAM caps
  steps/octree back down). Practical 8GB recipe: `balanced` + good input +
  texture on + a few seeds.

## Quick start (no GPU — mock mode)

Tests the full API + queue without downloading weights:

```bash
cd plushy-ai
pip install fastapi "uvicorn[standard]" python-multipart httpx pillow numpy trimesh
PLUSHY_MOCK=1 uvicorn app:app --reload --port 8000
```

```bash
# enqueue
curl -X POST http://localhost:8000/api/generate \
  -F "image=@test.png" -F "seed=42"
# → {"job_id":"a1b2c3d4e5f6","status":"queued","poll_url":"/api/status/a1b2c3d4e5f6",...}

# poll
curl http://localhost:8000/api/status/a1b2c3d4e5f6

# download
curl -OJ http://localhost:8000/api/result/a1b2c3d4e5f6
```

## GPU run (Docker)

```bash
docker build -t plushy-ai .
docker run --gpus all -p 8000:8000 \
  -e PLUSHY_BACKEND=trellis \        # or hunyuan3d
  -e HF_TOKEN=$HF_TOKEN \            # if a model is gated
  -v $PWD/outputs:/app/outputs \
  plushy-ai
```

First real generation downloads weights (~5–10 GB) and warms up — expect a
few minutes. After that, image→GLB is typically 30–60s on an RTX 4090.

### Backends

- **TRELLIS** (default, `PLUSHY_BACKEND=trellis`): `JeffreyXiang/TRELLIS-image-large`
  — best single-image quality. Override with `PLUSHY_TRELLIS_MODEL`.
- **Hunyuan3D-2** (`PLUSHY_BACKEND=hunyuan3d`): `tencent/Hunyuan3D-2`
  — needs the hy3dgen package:
  ```bash
  git clone https://github.com/Tencent/Hunyuan3D-2.git /opt/Hunyuan3D-2
  pip install -e /opt/Hunyuan3D-2
  ```

## Env vars

| Var | Default | Meaning |
|---|---|---|
| `PLUSHY_BACKEND` | `trellis` | `trellis` \| `hunyuan3d` |
| `PLUSHY_MOCK` | `0` | `1` = placeholder meshes, no GPU/weights |
| `PLUSHY_DEVICE` | `cuda` | torch device |
| `PLUSHY_WORKERS` | `1` | queue workers (keep 1 per GPU) |
| `PLUSHY_MAX_UPLOAD_MB` | `25` | upload cap |
| `PLUSHY_JOB_TTL_SEC` | `86400` | result retention |
| `PLUSHY_LOWVRAM` | `0` | `1` = 8GB-GPU mode: fp16 autocast, ≤12 steps, ≤128 octree, 384px input (see `lowvram_patch.py`) |

### 8GB VRAM (RTX 4060) tip

If a generation fails with CUDA out-of-memory, restart with `PLUSHY_LOWVRAM=1`
— same API, same outputs, just lighter settings. If it still OOMs, lower
`--steps` / `num_inference_steps` further or try `PLUSHY_BACKEND=hunyuan3d`.

## Pushing to GitHub

```bash
cd plushy-ai
git init -b main
git add app.py pipeline.py lowvram_patch.py Dockerfile requirements.txt README.md .dockerignore
git commit -m "Plushy AI: async image-to-GLB pipeline (TRELLIS/Hunyuan3D)"
git remote add origin https://github.com/espil/plushy-ai.git
git push -u origin main
```

## Notes

- `.GLB` output is cleaned: duplicate faces removed, floaters dropped,
  quadric decimation, centered + normalized to [-1, 1], Y-up — loads in
  Blender, three.js, and game engines without fixes.
- Queue is in-memory; for multi-instance or crash-safe queues, swap
  `asyncio.Queue` for Redis + arq/dramatiq (the worker function is already
  isolated in `pipeline.py`).
