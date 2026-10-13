# Character Customization — Full Batch (VSC, GPU PC)

All prompts are written and committed. You only run the commands below, in
order, from the VS Code integrated terminal (PowerShell) at the repo root.
Everything runs in Docker with the repo mounted, so results land in
`paperdoll/` on disk.

Style: MapleStory 2-like 3D chibi (`--style chibi`), blank faceless bodies,
8 directions. Direction order for every batch:
`S,SE,E,NE,N,NW,W,SW` (= prompt index p00..p07).

## 0. Update + build (once)

```powershell
git pull
docker build -t plushy-ai .
```

Close Ollama first (VRAM). If Docker says the GPU is not visible, see
GPU_RUNBOOK.md troubleshooting.

## 1. Blank bodies — 8 directions x 2 seeds x M/F = 32 images

```powershell
docker run --rm --gpus all -v "${PWD}:/app" -v plushy-hf:/root/.cache/huggingface plushy-ai python sprites.py --prompts prompts/char_body_male.txt --style chibi --seeds 2 --size 512 --output ./paperdoll/bodies/male
docker run --rm --gpus all -v "${PWD}:/app" -v plushy-hf:/root/.cache/huggingface plushy-ai python sprites.py --prompts prompts/char_body_female.txt --style chibi --seeds 2 --size 512 --output ./paperdoll/bodies/female
```

Wear steps below use the seed-0 bodies (`--body-pattern "*_s0.png"`).
If seed 1 looks better for a direction, rename that file to `*_s0.png`
(swap the two) before running step 2.

## 2. Wear items — img2img layers (44 prompts x 8 dirs x M/F = 704 layers)

Tops (strength 0.6):

```powershell
docker run --rm --gpus all -v "${PWD}:/app" -v plushy-hf:/root/.cache/huggingface plushy-ai python paperdoll.py batch --body-dir ./paperdoll/bodies/male --prompts prompts/char_items_tops.txt --strength 0.6 --directions S,SE,E,NE,N,NW,W,SW --body-pattern "*_s0.png" --out ./paperdoll/layers/tops/male
docker run --rm --gpus all -v "${PWD}:/app" -v plushy-hf:/root/.cache/huggingface plushy-ai python paperdoll.py batch --body-dir ./paperdoll/bodies/female --prompts prompts/char_items_tops.txt --strength 0.6 --directions S,SE,E,NE,N,NW,W,SW --body-pattern "*_s0.png" --out ./paperdoll/layers/tops/female
```

Bottoms (strength 0.6):

```powershell
docker run --rm --gpus all -v "${PWD}:/app" -v plushy-hf:/root/.cache/huggingface plushy-ai python paperdoll.py batch --body-dir ./paperdoll/bodies/male --prompts prompts/char_items_bottoms.txt --strength 0.6 --directions S,SE,E,NE,N,NW,W,SW --body-pattern "*_s0.png" --out ./paperdoll/layers/bottoms/male
docker run --rm --gpus all -v "${PWD}:/app" -v plushy-hf:/root/.cache/huggingface plushy-ai python paperdoll.py batch --body-dir ./paperdoll/bodies/female --prompts prompts/char_items_bottoms.txt --strength 0.6 --directions S,SE,E,NE,N,NW,W,SW --body-pattern "*_s0.png" --out ./paperdoll/layers/bottoms/female
```

Hair (strength 0.6) — Espil pink bob = p00, Lunaris silver = p01:

```powershell
docker run --rm --gpus all -v "${PWD}:/app" -v plushy-hf:/root/.cache/huggingface plushy-ai python paperdoll.py batch --body-dir ./paperdoll/bodies/male --prompts prompts/char_items_hair.txt --strength 0.6 --directions S,SE,E,NE,N,NW,W,SW --body-pattern "*_s0.png" --out ./paperdoll/layers/hair/male
docker run --rm --gpus all -v "${PWD}:/app" -v plushy-hf:/root/.cache/huggingface plushy-ai python paperdoll.py batch --body-dir ./paperdoll/bodies/female --prompts prompts/char_items_hair.txt --strength 0.6 --directions S,SE,E,NE,N,NW,W,SW --body-pattern "*_s0.png" --out ./paperdoll/layers/hair/female
```

Faces (strength 0.45 — face only, body stays put; Espil's own face excluded):

```powershell
docker run --rm --gpus all -v "${PWD}:/app" -v plushy-hf:/root/.cache/huggingface plushy-ai python paperdoll.py batch --body-dir ./paperdoll/bodies/male --prompts prompts/char_items_faces.txt --strength 0.45 --directions S,SE,E,NE,N,NW,W,SW --body-pattern "*_s0.png" --out ./paperdoll/layers/faces/male
docker run --rm --gpus all -v "${PWD}:/app" -v plushy-hf:/root/.cache/huggingface plushy-ai python paperdoll.py batch --body-dir ./paperdoll/bodies/female --prompts prompts/char_items_faces.txt --strength 0.45 --directions S,SE,E,NE,N,NW,W,SW --body-pattern "*_s0.png" --out ./paperdoll/layers/faces/female
```

Each output folder gets `worn_*.png` (full character), `layer_*.png`
(transparent item layer) and `manifest.json`.

## 3. Compose a test character (example: Espil, front/S)

```powershell
docker run --rm --gpus all -v "${PWD}:/app" -v plushy-hf:/root/.cache/huggingface plushy-ai python paperdoll.py compose --body ./paperdoll/bodies/female/p00_chibi-girl-character-huge-bald-head_s0.png --layers ./paperdoll/layers/tops/female/layer_S_p0_s0.png,./paperdoll/layers/hair/female/layer_S_p0_s0.png --out ./paperdoll/chars/espil_S.png
```

(Exact body filename depends on the generated slug — check the folder.)

## Expected totals

- Bodies: 32 PNG
- Layers: 704 worn + 704 layer PNG + 8 manifests
- Time on RTX 4060: bodies a few minutes; wear roughly 30-60 min total.
  Each category command can be stopped and re-run independently.
