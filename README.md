# Plushy AI

**Free, local AI asset generation for game developers - on your own GPU.**

Plushy AI turns text prompts into transparent game sprites, and images
into textured 3D models (GLB), entirely on your own machine. No cloud,
no per-generation fees, nothing uploaded anywhere.

## What it does

| Mode | Input | Output |
|---|---|---|
| Sprite generation | a text prompt | transparent PNG sprite (SDXL-Turbo + rembg), ~5 s on an RTX 4060 |
| Image to 3D | one image (plain white background works best) | textured GLB via Stable Fast 3D, decimated to a game triangle budget, meshopt-compressed **plus** an uncompressed twin for loaders without meshopt support (e.g. Unity glTFast) |
| Batch production | a folder of images + a JSON manifest | a whole set converted unattended and resumable |

3D budgets by default: 8,000 triangles per normal model, 20,000 for
landmarks, textures at 1024-2048.

## The Studio (web UI)

One page does everything: **Plushy AI Studio**

- Prompt box with live job progress
- Sprite and image-to-3D modes
- In-browser 3D preview of generated models
- Gallery of your output folder with downloads
- Job history and cancel

## Quick start

Requirements: an NVIDIA GPU (8 GB VRAM or more) and Docker Desktop
(or Docker Engine with the NVIDIA container toolkit).

```bash
git clone https://github.com/espil/plushy-ai.git
cd plushy-ai
docker compose up --build
```

Then open **http://localhost:8000/studio**.

A Hugging Face token is needed once, on the very first run, to download
the gated SDXL-Turbo model:

```bash
export HF_TOKEN=hf_...        # PowerShell: $env:HF_TOKEN = "hf_..."
docker compose up --build
```

All weights (sprite, background removal, 3D - about 18 GB total) are
downloaded visibly on the first run, cached in a Docker volume, and
used offline afterwards. Nothing downloads silently mid-job.

On Windows, `start-gui.bat` does the same thing and also serves the
Studio to other devices on your LAN.

## Batch 3D production

```bash
python run_buildings_3d.py --manifest waitemata_v2_manifest.json \
    --inputs inputs/waitemata_v2 --texture 2048 --out outputs/models3d_v2
```

Every asset produces `<name>.glb` (compressed),
`<name>_uncompressed.glb`, and a `<name>.glb.json` spec sidecar.
Re-running skips finished assets, so a batch can be stopped and
resumed at any point. Ready-made `run-*.bat` launchers are included.

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/sprite` | JSON `prompt`, `seed`, `size` (64-1024), `steps` - returns `202 { job_id }` |
| `POST` | `/api/model3d` | upload an image - returns `202 { job_id }` |
| `GET` | `/api/status/{job_id}` | `{ status, progress, message, result_url, elapsed_sec, error }` |
| `GET` | `/api/result/{job_id}` | download the result file |
| `GET` | `/api/outputs` | list generated files, newest first |
| `DELETE` | `/api/job/{job_id}` | cancel a job and delete its result |
| `GET` | `/studio` | the Studio web UI |
| `GET` | `/health` | liveness, queue depth, active output dir |

## Project layout

| File | Role |
|---|---|
| `app.py` | FastAPI server + async job queue (one GPU worker) |
| `static/studio.html` | the Studio web UI (single file) |
| `pipeline_sprite.py` | text to sprite (SDXL-Turbo, rembg) |
| `pipeline_3d.py` | image to 3D (Stable Fast 3D + gltfpack) |
| `run_buildings_3d.py` | resumable batch converter |
| `sprites.py` | batch sprite CLI |
| `prompts/` | production prompt sets from our own games |
| `docs/` | production standards and notes |

## Smoke test (no GPU)

```powershell
$env:PLUSHY_MOCK = "1"
python sprites.py --prompt "a pine tree" --output ./mock_sprites
```

`PLUSHY_MOCK=1` swaps generation for a placeholder so the whole
CLI to API to UI path can be tested without a GPU.

## Notes and limits

- 3D quality follows the source image: one clean object on a plain
  white background converts best.
- Conversion takes roughly 4 minutes per model on an RTX 4060.
- The LAN server has no login. Use it only on a trusted network and
  do not forward port 8000 to the internet.
- Outputs stay on your machine (the repo's `outputs` folder by
  default, or `PLUSHY_OUTPUT_DIR` when set).

## License

MIT - free for personal and commercial use. See `LICENSE`.

Plushy AI is made by [Espil](https://espil.online); it is the tool we
use to produce assets for our own games. If it helps you, a star on
the repo is the best thank-you.
