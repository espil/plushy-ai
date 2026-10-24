# 🧸 Plushy AI - local text-to-sprite generator

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
| `GET` | `/api/outputs` | lists PNGs already in the output folder, newest first |
| `DELETE` | `/api/job/{job_id}` | cancel + delete that job's result |
| `GET` | `/studio` | web UI: prompt → sprite → preview → download |
| `GET` | `/health` | liveness, queue depth and the active `output_dir` |

## Zealandia production prompt pack

The EverPlanet-inspired original production set for the whole route -
Waitematā, the six ruin villages, the nine field maps and the three
dungeons - is documented in `prompts/EVERPLANET_PRODUCTION_PACK.md`.

• `prompts/everplanet_waitemata_buildings.txt`
• `prompts/everplanet_waitemata_props.txt`
• `prompts/everplanet_characters.txt`
• `prompts/everplanet_dungeon_entrances.txt`
• `prompts/everplanet_dungeon_assets.txt`
• `prompts/everplanet_villages_buildings.txt`
• `prompts/everplanet_villages_props.txt`
• `prompts/everplanet_villages_characters.txt`
• `prompts/everplanet_field_landmarks.txt`

Run `git pull` on the GPU PC and the prompt files are ready. The Studio
launcher mounts the pulled repo into the container, so prompt updates are
available on the next server start without rebuilding the Docker image.

## Quick start (GPU PC, Docker + GPU)

```powershell
git pull
.\start-gui.bat
```

`start-gui.bat` is the normal live-server launcher.

• It publishes the server on the GPU PC and on the same LAN.
• Open `http://localhost:8000/studio` on the GPU PC.
• Open `http://<GPU PC LAN IP>:8000/studio` on a laptop on the same network.
• The GPU PC, Docker Desktop and the launcher window must stay on.
• If the laptop cannot connect, allow Docker Desktop or TCP port 8000 through Windows Firewall for the Private network.

## Output location: OneDrive

Studio generations are written to the first matching location below.

• `PLUSHY_OUTPUT_DIR`, when set before launch
• `%OneDrive%\Plushy AI\outputs` on the Windows GPU PC
• The repo's local `outputs` folder as a fallback

The launcher prints the active output folder before the server starts. Keep
OneDrive signed in and syncing on the GPU PC, then share the `Plushy AI`
folder from OneDrive with the Muse team. The Studio gallery reads the same
folder through `/api/outputs`, so the laptop can also browse and download the
results. Result PNGs are not deleted when old job records expire.

Batch CLI runs use the folder passed to `--output`; the production pack
shows PowerShell commands that place each batch under the same OneDrive
`Plushy AI\outputs` tree.

### One-off sprite (fastest path)

```powershell
docker run --rm --gpus all `
  -v "${PWD}/my_sprites:/app/my_sprites" `
  -v plushy-hf:/root/.cache/huggingface `
  plushy-ai python sprites.py --prompt "a pine tree" --output /app/my_sprites
```

The SDXL-Turbo model downloads once (~7GB) into the `plushy-hf` volume -
later runs reuse it.

### Batch from a prompts file

```powershell
docker run --rm --gpus all `
  -v "${PWD}/prompts.txt:/app/prompts.txt" `
  -v "${PWD}/my_sprites:/app/my_sprites" `
  -v plushy-hf:/root/.cache/huggingface `
  plushy-ai python sprites.py --prompts /app/prompts.txt --output /app/my_sprites --seeds 3 --size 256
```

## Local smoke test (no GPU, placeholder output)

```powershell
$env:PLUSHY_MOCK = "1"
python sprites.py --prompt "a pine tree" --output ./mock_sprites
```

`PLUSHY_MOCK=1` replaces generation with a checkerboard placeholder so the
full CLI → API → GUI path can be tested without a GPU.

## Notes

• Prompt tips: keep it simple - "a pine tree", "a wooden park bench".
• The pipeline appends `game sprite, centered, isolated on a plain white background` and strips the background automatically.
• First real generation takes a few minutes (model download); after that it's seconds.
• The LAN server has no login. Use it only on a trusted home or office network and do not forward port 8000 to the internet.
