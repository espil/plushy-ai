# Plushy AI - Sprite Runbook (RTX 4060, Windows)

Goal: generate real transparent-PNG sprites on the GPU PC, send prompts
from a laptop on the same network, and collect the results locally.

## 0. Prerequisites

• Docker Desktop for Windows, using the WSL2 backend
• NVIDIA drivers installed on Windows
• About 15 GB free disk for Docker layers and the one-time SDXL-Turbo download
• Close Ollama and GPU-heavy browser tabs before generating - the RTX 4060 has 8 GB VRAM, which is enough for SDXL-Turbo when other GPU work is closed

Verify the GPU is visible to Docker in PowerShell:

```powershell
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

## 1. Pull the latest prompts and code

```powershell
cd plushy-ai
git pull
```

The live server mounts this repo into the container, so newly pulled code
and prompt files apply when the server is restarted. Run
`docker build -t plushy-ai .` again only when the Dockerfile or
requirements changed.

## 2. Start the live server for the GPU PC and laptop

Double-click `start-gui.bat`, or run it from PowerShell:

```powershell
.\start-gui.bat
```

• GPU PC: `http://localhost:8000/studio`
• Laptop on the same LAN: `http://<GPU PC LAN IP>:8000/studio`
• The launcher prints the LAN addresses it finds.
• Keep the GPU PC, Docker Desktop and the launcher window on while working from the laptop.
• The laptop uses the Studio in its browser to send prompts, watch progress, browse `/api/outputs` results and download PNGs.
• If the laptop cannot connect, allow Docker Desktop or TCP port 8000 through Windows Firewall on the Private network.
• There is no login on the LAN server. Use it only on a trusted network and do not forward port 8000 to the internet.

## 3. Output folder (local)

The Studio writes to the repo's `outputs` folder by default. The launcher
prints the exact active folder before starting.

To use a different folder for one launch, set it before running the launcher:

```powershell
$env:PLUSHY_OUTPUT_DIR = "D:\PlushyOutputs"
.\start-gui.bat
```

Result PNGs remain in the folder when old job records expire. Batch
folders and `manifest.json` files live under the same local tree.

## 4. First sprite from the command line

```powershell
docker run --rm --gpus all `
  -v "${PWD}/my_sprites:/app/my_sprites" `
  -v plushy-hf:/root/.cache/huggingface `
  plushy-ai python sprites.py --prompt "a pine tree" --output /app/my_sprites
```

The first run downloads SDXL-Turbo into the `plushy-hf` volume once. Later
runs reuse it.

## 5. Run the EverPlanet-inspired Zealandia pack

Read `prompts/EVERPLANET_PRODUCTION_PACK.md` first. It gives the file order,
style locks and output subfolders. The PowerShell pattern below mounts the
pulled repo and its local output tree, so the batch uses the newest
prompts and the PNGs sync after generation.

```powershell
$OutRoot = Join-Path $PWD "outputs"
New-Item -ItemType Directory -Force $OutRoot | Out-Null

docker run --rm --gpus all `
  -v "${PWD}:/app" `
  -v "${OutRoot}:/app/plushy_outputs" `
  -v plushy-hf:/root/.cache/huggingface `
  plushy-ai python sprites.py `
    --prompts /app/prompts/everplanet_waitemata_buildings.txt `
    --subject-type building --style 2.5d --seeds 2 --size 768 `
    --output /app/plushy_outputs/waitemata_buildings
```

Repeat with the other prompt files and commands from the production pack.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `could not select device driver` or no GPU in `nvidia-smi` | Docker Desktop Settings, Resources, GPU - enable it and restart Docker |
| CUDA out of memory | Close Ollama and GPU-heavy apps; lower the batch size to 512 or 256 |
| Laptop cannot open the Studio | Check both machines are on the same LAN, the GPU PC is awake, Docker is running, and Windows Firewall allows port 8000 on Private networks |
| New prompt file is missing in a one-off Docker run | Mount the repo with `-v "${PWD}:/app"` as in section 5, or rebuild the image |
| New files do not appear in outputs | Confirm the launcher printed the expected local output folder and that the batch used the same folder |
| Blank or white sprite | Keep the prompt concrete, for example "a pine tree" or "a red fire hydrant" |
| A job stays in processing | First run downloads the gated SDXL-Turbo model (~7 GB) plus the rembg model: watch the launcher console for `loading sprite model` and download progress, and check GPU use in Task Manager. If the log shows 401/gated, stop the launcher, set `HF_TOKEN` in PowerShell (`$env:HF_TOKEN = "..."`), and start again - the launcher forwards it to the container. |

## 3D pipeline (image -> GLB, SF3D) - added 2026-10-25

The Studio has an "Image -> 3D model" card: upload one image, get a
textured GLB back. The engine is Stable Fast 3D (SF3D), running locally
in an isolated venv inside the image (/opt/sf3d-venv). No cloud, no
per-use credits. About 6GB VRAM per image; a few seconds per model once
the model is downloaded.

One-time setup:

1. Rebuild the image (the Dockerfile changed - devel base + SF3D venv).
   The first build takes a while (two torch installs + compiling SF3D's
   texture baker):
       docker build -t plushy-ai .
2. Grant model access once, on the same Hugging Face account as your
   HF_TOKEN: open https://huggingface.co/stabilityai/stable-fast-3d and
   accept the model terms ("Agree and access repository").
3. Keep HF_TOKEN set when launching (start-gui.bat forwards it). The
   first real 3D run downloads the model (~3GB) into the plushy-hf
   volume; later runs reuse it.

Verify before trusting it - run `selftest-3d.bat`. It converts a drawn
test house and checks the GLB numerically (triangle count, bounding
box, texture present). It prints SELFTEST PASS only for a real textured
mesh; the old gray-sphere placeholder can never pass.

Mock rule: with PLUSHY_MOCK=1 the 3D path returns a file named
*_MOCK.glb with a "mock": true sidecar, and the Studio says so. With
mock off, a missing engine or a failed check fails the job loudly - a
placeholder is never substituted silently.

Building spec applied automatically (Han, 2026-10-25): every model3d
job is decimated to its triangle budget and gltfpack-compressed before
delivery - normal buildings <= 8000 triangles, landmarks <= 20000
(tick "Landmark" in the Studio card), textures baked at <= 1024.
The delivered GLB's sidecar .json records the final triangle count
and budget.
