# 2D Character - SAMPLE Batch (Plushy AI, GPU PC) - corrected 2026-11-10

The first char2d batch (12 poses at once) produced garbage and is discarded.
This batch is the sample only: ONE body pose, the 3 wear items, the weapon.
Nothing expands until this sample passes Han's verdict in the asset room.

Run from the VS Code integrated terminal (PowerShell) at the repo root.

## 0. Update + build (once)

```powershell
git pull
docker build -t plushy-ai .
```

Close Ollama first (VRAM).

## 1. Sample body - side stand, 4 seeds

```powershell
docker run --rm --gpus all -v "${PWD}:/app" -v plushy-hf:/root/.cache/huggingface plushy-ai python sprites.py --prompts prompts/char2d_sample_body.txt --style 2.5d --seeds 4 --size 1024 --output ./char2d-sample/bodies/male
```

Look at the 4 results. Keep the best one as `*_s0.png`: if another seed looks
better, rename it to `*_s0.png` (swap the two filenames) before step 2.

## 2. Wear items on the picked body (hair, bottom, shoes)

```powershell
docker run --rm --gpus all -v "${PWD}:/app" -v plushy-hf:/root/.cache/huggingface plushy-ai python paperdoll.py batch --body-dir ./char2d-sample/bodies/male --prompts prompts/char2d_items_male.txt --strength 0.6 --style 2.5d --directions stand --body-pattern "*_s0.png" --out ./char2d-sample/layers/male
```

## 3. Weapon - ice longsword, 2 seeds

```powershell
docker run --rm --gpus all -v "${PWD}:/app" -v plushy-hf:/root/.cache/huggingface plushy-ai python sprites.py --prompts prompts/char2d_weapon.txt --style 2.5d --seeds 2 --size 1024 --output ./char2d-sample/weapons
```

## 4. Send the results back

```powershell
git add char2d-sample
git commit -m "char2d sample outputs"
git push
```

If the push fails because of size, send the `char2d-sample` folder to the asset
room directly instead.
