# Plushy AI — Sprite Runbook (RTX 4060, Windows)

Goal: generate your first real transparent-PNG sprite on your GPU.
Expected time: ~20–30 min first run (mostly one-time downloads), seconds after.

## 0. Prerequisites

- Docker Desktop for Windows, using the **WSL2 backend**
- NVIDIA drivers installed on Windows (you have them — Ollama uses the GPU)
- ~15 GB free disk (Docker layers + SDXL-Turbo weights, ~7GB once)
- **Close Ollama and GPU-heavy browser tabs** before generating — 8GB VRAM
  is plenty for SDXL-Turbo, but Ollama holds VRAM by default

Verify the GPU is visible to Docker (PowerShell):

```powershell
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

## 1. Pull and build

```powershell
cd plushy-ai   # wherever you cloned the repo
git pull
docker build -t plushy-ai .
```

## 2. First sprite

```powershell
docker run --rm --gpus all `
  -v "${PWD}/my_sprites:/app/my_sprites" `
  -v plushy-hf:/root/.cache/huggingface `
  plushy-ai python sprites.py --prompt "a pine tree" --output /app/my_sprites
```

Watch the log: first run downloads SDXL-Turbo into the `plushy-hf` volume
(one time, a few minutes), then generates. Output: `my_sprites/a_pine_tree.png`
with a transparent background.

## 3. Batch

Write `prompts.txt` (one per line, `#` = comment), then:

```powershell
docker run --rm --gpus all `
  -v "${PWD}/prompts.txt:/app/prompts.txt" `
  -v "${PWD}/my_sprites:/app/my_sprites" `
  -v plushy-hf:/root/.cache/huggingface `
  plushy-ai python sprites.py --prompts /app/prompts.txt --output /app/my_sprites --seeds 3 --size 256
```

You get PNGs + `manifest.json` (prompt, seed, file per entry).

## 4. Web UI

```powershell
docker run --rm --gpus all -p 8000:8000 -v plushy-hf:/root/.cache/huggingface plushy-ai
```

Open http://localhost:8000/studio — type a prompt, watch progress,
download the PNG.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `could not select device driver` / no GPU in `nvidia-smi` | Docker Desktop → Settings → Resources → GPU (enable), restart Docker |
| CUDA out of memory | Close Ollama/browser; sprites rarely OOM — if it happens, `--size 256` |
| Slow first run | Model download; check with `docker stats` — it only happens once per volume |
| Blank/white sprite | Prompt too abstract — keep it concrete ("a pine tree", "a red fire hydrant") |
