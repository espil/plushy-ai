# 🧸 Plushy AI — local text-to-sprite generator

Text prompt → transparent PNG sprites, generated on your own GPU.
No cloud, no per-generation fees. Built for billboard sprites in game maps
(trees, props, street furniture).

```
"a pine tree" ──▶ POST /api/sprite ──▶ queue ──▶ SDXL-Turbo + rembg ──▶ sprite.png
```

~5 seconds per sprite on an RTX 4060 (8GB).

## Architecture

| Piece | File | Notes |
|---|---|---|
| API + async queue | `app.py` | FastAPI; `POST /api/sprite` returns `202 + job_id` immediately; background workers (default 1, one GPU) run inference in a thread executor so the event loop never blocks |
| Sprite pipeline | `pipeline_sprite.py` | SDXL-Turbo text-to-image → rembg background removal → transparent `.PNG` (fp16 on CUDA, xformers attention when available) |
| Batch CLI | `sprites.py` | prompts file → folder of transparent PNGs + `manifest.json` |
| GPU environment | `Dockerfile` | CUDA 12.1 runtime, torch 2.3, diffusers |

### Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/sprite` | JSON `prompt`, `seed`, `size` (64–1024), `steps` → `202 { job_id, poll_url }` |
| `GET` | `/api/status/{job_id}` | `{ status, progress, message, result_url, elapsed_sec, error }` |
| `GET` | `/api/result/{job_id}` | downloads the transparent `.PNG` (`image/png`) |
| `DELETE` | `/api/job/{job_id}` | cancel + delete |
| `GET` | `/studio` | web UI: prompt → sprite → preview → download |
| `GET` | `/health` | liveness, queue depth |

## Quick start (your PC, Docker + GPU)

```powershell
git pull
docker build -t plushy-ai .
```

### One-off sprite (fastest path)

```powershell
docker run --rm --gpus all `
  -v "${PWD}/my_sprites:/app/my_sprites" `
  -v plushy-hf:/root/.cache/huggingface `
  plushy-ai python sprites.py --prompt "a pine tree" --output /app/my_sprites
```

The SDXL-Turbo model downloads once (~7GB) into the `plushy-hf` volume —
later runs reuse it.

### Batch from a prompts file

```powershell
docker run --rm --gpus all `
  -v "${PWD}/prompts.txt:/app/prompts.txt" `
  -v "${PWD}/my_sprites:/app/my_sprites" `
  -v plushy-hf:/root/.cache/huggingface `
  plushy-ai python sprites.py --prompts /app/prompts.txt --output /app/my_sprites --seeds 3 --size 256
```

### Web UI

```powershell
docker run --rm --gpus all -p 8000:8000 -v plushy-hf:/root/.cache/huggingface plushy-ai
```

Open http://localhost:8000/studio — type a prompt, get the sprite, download it.

## Local smoke test (no GPU, placeholder output)

```powershell
$env:PLUSHY_MOCK = "1"
python sprites.py --prompt "a pine tree" --output ./mock_sprites
```

`PLUSHY_MOCK=1` replaces generation with a checkerboard placeholder so the
full CLI → API → GUI path can be tested without a GPU.

## Notes

- Prompt tips: keep it simple — "a pine tree", "a wooden park bench".
  The pipeline appends `game sprite, centered, isolated on a plain white background`
  and strips the background automatically.
- First real generation takes a few minutes (model download); after that it's seconds.
