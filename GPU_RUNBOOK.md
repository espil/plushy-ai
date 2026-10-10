# Plushy AI — First Real GPU Test Runbook (RTX 4060, Windows)

Goal: run the **actual** TRELLIS model on your GPU and find out where Plushy
really stands vs Meshy. Every mock test so far proves the plumbing; this is
the first test of the water.

Expected time: ~30–60 min total (mostly one-time downloads).

---

## 0. Prerequisites

- Docker Desktop for Windows, using the **WSL2 backend**
  (Settings → General → "Use the WSL 2 based engine" checked)
- NVIDIA drivers installed on Windows (you have them — Ollama uses the GPU)
- ~30 GB free disk (Docker layers + model weights)
- **Close Ollama and GPU-heavy browser tabs** before generating — 8 GB VRAM
  is the TRELLIS minimum and Ollama holds VRAM by default

Verify the GPU is visible to Docker (PowerShell):

```powershell
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

If that fails, GPU support isn't wired up — fix that before continuing
(Docker Desktop docs: "GPU support in Docker Desktop / WSL2").

---

## 1. Get the code

Unzip `plushy-ai.zip` somewhere, e.g. `C:\plushy-ai`. You should see
`app.py`, `batch.py`, `pipeline.py`, `Dockerfile`, etc.

---

## 2. Build the image (one time, ~10–20 min)

```powershell
cd C:\plushy-ai
docker build -t plushy-ai .
```

This installs CUDA torch, TRELLIS from source, and all deps. Go make coffee.

---

## 3. Prepare test inputs — this decides 80% of the quality

Put 2–3 images in `C:\plushy-ai\my_art\`. Pick subjects you can **compare
against a Meshy result** — ideally something you already generated with
Meshy, so the A/B is direct.

**What makes a good input** (matters more than any setting):

- Plain background — white or light gray. Busy backgrounds confuse the model
- 3/4 front view, single subject, centered, fills ~70% of the frame
- Even lighting, no harsh shadows; 512px or larger; no text/watermarks

**For clothing (Musinsa streetwear direction):**

- Flat-lay (garment laid flat, shot top-down) or ghost-mannequin product
  shots — the way Musinsa lists products, ironically, is ideal input
- Do **not** use a photo of a person wearing the garment — the model will
  try to build the person too
- One garment per image; front view; original designs (your IP, not
  scraped product photos)

---

## 4. Test 1 — baseline (does it run?)

```powershell
docker run --rm --gpus all `
  -v ${PWD}/my_art:/app/my_art `
  -v ${PWD}/my_glbs:/app/my_glbs `
  -v plushy-hf:/root/.cache/huggingface `
  plushy-ai python batch.py --input /app/my_art --output /app/my_glbs --seed 0
```

Notes:

- First run downloads ~5–10 GB of weights (HuggingFace, no login needed).
  The `plushy-hf` volume keeps them cached — **don't skip it**, or every
  `--rm` run re-downloads.
- In a **second PowerShell window**, watch VRAM live: `nvidia-smi -l 2`
- Expect ~30–90 s per image on a 4060 after warmup.

Result: `my_glbs\<name>.glb` + `manifest.json`. Open the GLB in Windows'
built-in 3D Viewer, Blender, or https://gltf-viewer.donmccurdy.com/.

---

## 5. Test 2 — seed lottery (biggest quality lever after input)

Same image, three seeds, keep the winner:

```powershell
docker run --rm --gpus all `
  -v ${PWD}/my_art:/app/my_art -v ${PWD}/my_glbs:/app/my_glbs `
  -v plushy-hf:/root/.cache/huggingface `
  plushy-ai python batch.py --input /app/my_art --output /app/my_glbs_seeds `
    --seed 0
# then --seed 1, then --seed 2 (change --output each time or use --skip-existing off)
```

Quality varies more seed-to-seed than between most settings. This is
Meshy's "refine" loop, done manually.

---

## 6. Test 3 — quality preset (only if baseline works)

```powershell
docker run --rm --gpus all `
  -v ${PWD}/my_art:/app/my_art -v ${PWD}/my_glbs:/app/my_glbs `
  -v plushy-hf:/root/.cache/huggingface `
  plushy-ai python batch.py --input /app/my_art --output /app/my_glbs_hq `
    --quality detailed --seed <best-seed-from-test-2>
```

`detailed` = 50 steps, octree 512. **Likely to OOM on 8 GB.** That's
expected — see troubleshooting.

---

## 7. How to evaluate (the Meshy comparison)

For each GLB, score honestly 1–5:

1. **Silhouette** — does the shape read as the subject? No extra limbs,
   melted blobs, or hollow backside?
2. **Texture** — do the colors/patterns match the input? (This is where
   Meshy usually wins — judge it separately from geometry.)
3. **Usability** — would you wear/place this in Espil Online as-is, with
   light cleanup, or not at all?

Then put your Meshy GLB of the same (or similar) subject next to the
winner. Note *specifically* where Meshy wins — "texture detail on fabric",
"cleaner edges", whatever it is. That list becomes our improvement backlog.

Record for the winner: seed, quality preset, time per image, peak VRAM
from your `nvidia-smi` watch.

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `CUDA out of memory` | Add `-e PLUSHY_LOWVRAM=1` to `docker run`; close Ollama/browser; drop to `--quality draft` |
| Still OOM in low-VRAM mode | `--steps 12 --octree 128` explicitly; last resort: `PLUSHY_MOCK=1` just to test plumbing (placeholder geometry) |
| Weights re-download every run | You forgot `-v plushy-hf:/root/.cache/huggingface` |
| `docker: --gpus` not recognized | Docker Desktop WSL2 backend + NVIDIA container toolkit; re-run the `nvidia-smi` check from step 0 |
| Build fails on TRELLIS/spconv | Re-run `docker build` (transient network flakes are common); check Docker has ≥4 GB RAM allocated in Settings → Resources |
| Generation is slow (>3 min/img) | First image includes warmup; check `nvidia-smi` — if GPU util is 0%, the container isn't seeing the GPU |

---

## 9. Optional: API server instead of CLI

Same image, server mode (for the `/api/batch` multi-upload flow):

```powershell
docker run --rm --gpus all -p 8000:8000 `
  -v plushy-hf:/root/.cache/huggingface `
  plushy-ai
```

Then `POST http://localhost:8000/api/batch` with your images
(docs at `http://localhost:8000/docs`).

---

## 10. Report back

Tell me: the winner's seed/settings, time + peak VRAM, and the 1–5 scores
— especially *where Meshy won*. That's the input I need to plan the next
quality push (options on the table: Hunyuan3D backend comparison, texture
pipeline tuning, input preprocessing upgrades).
