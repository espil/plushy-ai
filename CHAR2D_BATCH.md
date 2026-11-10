# SUPERSEDED 2026-11-10 - this batch produced garbage and is discarded. Use CHAR2D_SAMPLE.md.

# 2D Character - Perfection Line Batch (Plushy AI, GPU PC)

Production route decided by Han (2026-11-10): the 2D character line is produced
with Plushy AI. All prompts are written and committed. You only run the commands
below, in order, from the VS Code integrated terminal (PowerShell) at the repo
root. Everything runs in Docker with the repo mounted, so results land in
`char2d/` on disk.

Concept: prompts/DESIGN-CONCEPT-v1.md - one master palette, 2.5D EverPlanet
proportion (head one third of height), flat cel shading in 4 value steps, warm
dark outlines, low file weight. Finishing (Ground Zero alignment, part
registration, palette gate) happens in the asset room after generation, so the
only thing this batch must produce is clean generations.

This batch is the SAMPLE look (male): bodies for 12 poses, 3 wear items
(hair, bottom, shoes), and the ice longsword. The top slot is not in this batch
on purpose - its design is still open. The face marks are not generated here;
they stay an asset-room layer.

## 0. Update + build (once)

```powershell
git pull
docker build -t plushy-ai .
```

Close Ollama first (VRAM). If Docker says the GPU is not visible, see
GPU_RUNBOOK.md troubleshooting.

## 1. Bodies - 12 poses x 2 seeds = 24 images

```powershell
docker run --rm --gpus all -v "${PWD}:/app" -v plushy-hf:/root/.cache/huggingface plushy-ai python sprites.py --prompts prompts/char2d_body_male.txt --style 2.5d --seeds 2 --size 1024 --output ./char2d/bodies/male
```

Pose order in the file: stand, walk1-4, alert, jump, prone (side, facing left),
then front stand/walk, back stand/walk. Wear steps below use the seed-0 bodies
(`--body-pattern "*_s0.png"`). If seed 1 looks better for a pose, rename that
file to `*_s0.png` (swap the two) before running step 2.

## 2. Wear items - 12 bodies x 3 items = 36 layers (strength 0.6)

```powershell
docker run --rm --gpus all -v "${PWD}:/app" -v plushy-hf:/root/.cache/huggingface plushy-ai python paperdoll.py batch --body-dir ./char2d/bodies/male --prompts prompts/char2d_items_male.txt --strength 0.6 --style 2.5d --directions stand,walk1,walk2,walk3,walk4,alert,jump,prone,fstand,fwalk,bstand,bwalk --body-pattern "*_s0.png" --out ./char2d/layers/male
```

Each run saves both the worn composite and the extracted item layer, plus a
manifest.json.

## 3. Weapon - ice longsword, 2 seeds

```powershell
docker run --rm --gpus all -v "${PWD}:/app" -v plushy-hf:/root/.cache/huggingface plushy-ai python sprites.py --prompts prompts/char2d_weapon.txt --style 2.5d --seeds 2 --size 1024 --output ./char2d/weapons
```

## 4. Send the results back

Commit and push the generated folder so the asset room can finish and gate it:

```powershell
git add char2d
git commit -m "char2d sample batch outputs"
git push
```

If the push fails because of size, send the `char2d` folder to the asset room
directly instead.
