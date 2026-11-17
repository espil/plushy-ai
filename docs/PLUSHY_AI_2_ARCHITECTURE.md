# Plushy-AI 2.0 — Architecture and Phase 0 Audit

Status: Phase 0 audit, recorded 2026-11-17 on branch `feature/plushy-ai-2.0`
(base: `main` @ `9949309` "Discard CHAR2D_SAMPLE.md (Han decision 2026-11-10)").
This document records what actually exists in the repository today. Anything
not verified by running it is marked **UNVERIFIED**.

## Product direction (Han, 2026-11-17)

Plushy-AI 2.0 began as an internal Espil Online asset-production studio.
Han's direction update of 2026-11-17: **the finished tool will be sold — it
is a commercial product, not internal-only.** This run records the direction
only; licensing, packaging, and any scope changes that follow from it belong
to later phases and are not redesigned here.

The 2.0 goal stands as written in the development prompt: an operator feeds a
reference image, picks a category and target region, and the tool generates,
reviews, fits (paper doll), and exports character/item assets that follow
Espil's real asset standards — standards that are **not yet established from
real reference assets**, so unspecified values stay `unknown`/`null` in every
2.0 artifact until real assets are analyzed.

## Repository audit (Phase 0)

### Layout (verified by direct inspection)

| Path | Role |
|---|---|
| `app.py` | FastAPI server + async job queue (single GPU worker by default) |
| `pipeline_sprite.py` | Text→sprite pipeline (SDXL-Turbo + rembg); mock backend under `PLUSHY_MOCK=1`; also img2img |
| `pipeline_3d.py` | Image→3D pipeline (Stable Fast 3D + gltfpack), separate SF3D venv in Docker |
| `paperdoll.py` | Paper-doll CLI: `wear` / `batch` / `compose` subcommands on top of `pipeline_sprite` |
| `sprites.py` | Batch text-to-sprite CLI (prompt files, seeds, manifest) |
| `crisp_sprites.py` | Alpha binarization post-processing for existing PNGs |
| `static/studio.html` | Studio web UI, single file (15,343 bytes) |
| `prompts/` | Production prompt sets, incl. `char_body_male/female.txt`, `char_items_tops/bottoms/hair/faces.txt` |
| `CHAR_CUSTOM_BATCH.md` | Character batch procedure (bodies → wear → compose) |
| `docs/standard/` | Existing Plushy production standards (3D/production line: asset/building/character/environment/monster/animation standards + asset manifest/schema JSON). These govern the existing 3D batch line; they are **not** the Espil Online 2D asset standard that 2.0 Phase 1 measures, and 2.0 does not treat them as such |
| `tools/` | `run_all_3d.py`, `prefetch_3d.py`, `selftest_3d.py`, `glb-viewer.html` |
| `inputs/`, `outputs/` | Batch input images; generated outputs (gitignored) |
| `Dockerfile`, `docker-compose.yml` | CUDA 12.1 image; torch 2.3.1 main env + torch 2.4.1 SF3D venv |

There is **no test suite** in the repository: no `tests/` directory and no
`test_*.py` files anywhere. Phase 1 introduces the first tests under `tests/`
(stdlib `unittest`, so they run without adding a test-runner dependency).

There are **no `.ase` / `.aseprite` files** anywhere in the repository.
Phase 1 therefore validates its Aseprite parser against a synthetic fixture
built to the published Aseprite file-format specification, and every field
that would require a real Espil asset stays `unknown`.

### Dependencies

`requirements.txt`: FastAPI 0.115.6, uvicorn 0.34.0, pydantic 2.10.4,
python-multipart, httpx, aiofiles, tqdm; Pillow 11.1.0, numpy 1.26.4,
rembg 2.0.57, onnxruntime-gpu; diffusers 0.31.0, accelerate, transformers
4.46.3, xformers (torch 2.3.x installed separately in the Dockerfile, CUDA
12.1 build). The Phase 1 analyzer deliberately uses only **Pillow + the
Python standard library**, so asset analysis runs anywhere the repo runs,
including machines without a GPU or the diffusion stack.

### Existing API contract (from `app.py` — must stay backward compatible)

| Method | Path | Contract |
|---|---|---|
| POST | `/api/sprite` | JSON `{prompt, seed, size (64–1024), steps, negative_prompt?, style}` → `202 {job_id, status, poll_url, message}` |
| POST | `/api/img2img` | multipart `image` (≤20 MB) + `prompt, seed, steps, strength, style, negative_prompt?` → `202 {job_id}` |
| POST | `/api/model3d` | multipart `image` (≤20 MB) + `texture_resolution (512/1024/2048), landmark` → `202 {job_id}` |
| GET | `/api/status/{job_id}` | `{job_id, status, progress, message, result_url, error, elapsed_sec}`; 404 unknown job |
| GET | `/api/result/{job_id}` | result file (PNG `image/png` or GLB `model/gltf-binary`); 409 not ready, 410 file gone |
| GET | `/api/outputs` | `{count, outputs:[{name, url, kind, size_bytes, mtime}]}` newest first |
| GET | `/api/outputs/{name}` | one output file; directory part stripped (no traversal) |
| DELETE | `/api/job/{job_id}` | cancels the job and deletes its result file |
| GET | `/health` | liveness, queue depth, output dir, model3d engine state |
| GET | `/studio`, `/` | Studio UI / index JSON |

Job lifecycle: `queued → processing → completed | failed | cancelled`.
Jobs live in memory; a janitor expires records after `PLUSHY_JOB_TTL_SEC`
(24 h) but keeps result files on disk. Outputs land in `PLUSHY_OUTPUT_DIR`
when set, else the repo-local `outputs/`; sprite results are named
`<job_id>.sprite.png`, 3D results `<job_id>.model3d.glb`, uploads are kept
under `outputs/uploads/` as `<job_id>_init.png` / `<job_id>_src.png`.

### File-output conventions (existing)

- `sprites.py`: `<output>/p{NN}_{slug}_s{seed}.png` per prompt/seed plus
  `manifest.json`.
- `paperdoll.py batch`: `worn_{DIR}_p{pi}_s{seed}.png` (full character) and
  `layer_{DIR}_p{pi}_s{seed}.png` (transparent item layer) plus
  `manifest.json` entries `{prompt, body, direction, seed, worn, layer}`.
- `paperdoll.py compose`: layer order hair_back, body, bottoms, tops, shoes,
  face, hair_front; layers are resized to the body canvas when sizes differ
  (2.0 Phase 4 will validate instead of silently resizing — later phase).
- Direction order everywhere: `S, SE, E, NE, N, NW, W, SW` (prompt index
  p00..p07). 2.0 keeps this order and naming.

### Studio UI (existing)

`static/studio.html` covers: prompt, negative prompt, optional base image
(img2img) with strength, size, seed, steps, style select
(`default | 2.5d | 3d | chibi`), job status polling, result gallery,
image-to-3D panel, job history and cancel. 2.0 Phase 6 extends this page;
it is not replaced blind.

## Baseline state (actually run, 2026-11-17, this machine)

| Check | Command | Result |
|---|---|---|
| Syntax | `python3 -m py_compile app.py paperdoll.py pipeline_sprite.py pipeline_3d.py sprites.py crisp_sprites.py` | PASS (all six compile) |
| Existing test suite | — | **None exists** in the repo (nothing to run) |
| Mock smoke (README no-GPU path) | `PLUSHY_MOCK=1 python3 sprites.py --prompt "a pine tree" --output /tmp/plushy_mock_out` | PASS — 1/1 sprite generated, `manifest.json` written |
| API server | `uvicorn app:app` | **UNVERIFIED here** — `fastapi` is not installed in this VM's system Python and there is no GPU; the Docker path is the documented route and was not run |
| GPU generation (SDXL-Turbo, rembg, SF3D) | — | **UNVERIFIED** — no GPU / model weights in this environment |

Local environment note: system Python 3.12.3 with Pillow 10.2.0 (repo pins
Pillow 11.1.0 in `requirements.txt`; the Phase 1 analyzer uses only stable
Pillow APIs present in both).

## Phase 1 deliverable (this branch)

`asset_standard/` — the Asset Standard Engine:

- PNG analysis: canvas size, color mode, alpha presence, content bounding
  box of non-transparent pixels, palette for indexed images.
- Aseprite analysis: a pure-stdlib parser for the published `.ase/.aseprite`
  format — header (canvas, color depth, frame count), frames (duration,
  chunk count), layer chunks (name, order, visibility, type, child level,
  blend mode, opacity), cel chunks (layer index, position, size, opacity,
  type), palette chunks (current 0x2019 and legacy 0x0011/0x0004). Chunk
  types the parser does not extract are **reported as warnings**, never
  silently skipped; structural corruption raises an error.
- Output: one versioned JSON per asset following the prompt's schema
  (`schema_version: "1.0"`); anything not measurable stays `null`.
  `anchors`, `directions`, and `style_profile` are emitted empty/null —
  they require real Espil reference assets and are never guessed.
- Originals are opened read-only and never modified.
- CLI: `tools/aseprite_analyzer.py <file...> [--out DIR]` writes
  `<asset_id>.asset_standard.json` per input and prints a summary + warnings.
- Tests: `tests/test_asset_standard.py` (stdlib `unittest`).

## What 2.0 does not change

Existing endpoints, the paper-doll batch/compose behavior and its output
names, the direction order, and the Studio's current workflow all stay as
they are. New 2.0 endpoints (prompt §5) arrive in their own phases and must
not collide with the contract table above.
