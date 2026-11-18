# Plushy-AI 2.0 - Development Guide

How the 2.0 work is organized, how to run it, and how to test it.
Companion docs: `docs/PLUSHY_AI_2_ARCHITECTURE.md` (Phase 0 audit),
`docs/ASSET_STANDARD.md` (Phase 1), `docs/REFERENCE_WORKFLOW.md`
(Phase 2), `docs/STYLE_AND_GENERATION.md` (Phase 3),
`docs/PAPERDOLL_FIT.md` (Phase 4), `docs/ASEPRITE_IMPORT_EXPORT.md`
(Phase 5), `docs/STUDIO2.md` (Phase 6).

## The separation rule (binding for all 2.0 work)

2.0 is housed SEPARATELY from 1.0 and never overwrites it:

- Every phase adds NEW files only. No 1.0 file (`app.py`,
  `pipeline_sprite.py`, `pipeline_3d.py`, `paperdoll.py`,
  `sprites.py`, `crisp_sprites.py`, `static/studio.html`,
  `Dockerfile`, `requirements.txt`, ...) and no earlier-phase
  2.0 file is ever modified by a later phase.
- Where the prompt says "extend" a 1.0 module, the work is a new
  2.0-side module that REUSES the 1.0 code by importing it
  (e.g. `fitting` imports `paperdoll`'s compose order;
  `generator` imports `pipeline_sprite` lazily).
- Check before every commit: `git diff --name-status main` must
  show additions (`A`) only.
- Housekeeping trap: running Python in this repo can dirty the
  tracked `__pycache__/*.pyc` files. Restore them before
  committing: `git checkout -- __pycache__` (and any package
  `__pycache__` that shows as modified).

## Layout (2.0 additions only)

| Path | Phase | What |
|---|---|---|
| `asset_standard/` + `tools/aseprite_analyzer.py` | 1 | Asset Standard Engine: PNG/Aseprite analysis to versioned JSON |
| `reference/` + `tools/reference_analyzer.py` | 2 | Validated reference upload, mask suggestion/edit/save, generation-target gate |
| `generator/` + `tools/asset_generator.py` | 3 | Style profiles (data), category templates, generation jobs over `pipeline_sprite` |
| `fitting/` + `tools/paperdoll_fit.py` | 4 | Paper-doll fitting with validated sizes, 8-direction accounting, sha256 generation linkage |
| `exporter/` + `tools/export_assets.py` | 5 | PNG copies, sprite sheet, layered .aseprite (own writer, Phase 1 round-trip verified) |
| `studio2/` + `studio2_server.py` + `static/studio2.html` | 6 | Service layer, thin FastAPI router, standalone entrypoint, 9-screen Studio page |
| `tests/` | 1-6 | stdlib `unittest` suites, one file per phase |

## Running

Libraries + CLIs need only Python 3 + Pillow (the Phase 1-6 code
deliberately avoids new dependencies):

```bash
python3 tools/aseprite_analyzer.py path/to/file.png
python3 tools/reference_analyzer.py path/to/ref.png --category Top
PLUSHY_MOCK=1 python3 tools/asset_generator.py "a red hoodie" --category Top
python3 tools/paperdoll_fit.py --help
python3 tools/export_assets.py --help
```

The Studio (Phase 6) additionally needs the 1.0 serving stack
(FastAPI + uvicorn, already required by `app.py`):

```bash
PLUSHY_MOCK=1 python3 studio2_server.py   # http://localhost:8000/studio2
```

`studio2_server.py` mounts the 2.0 router on the unmodified 1.0
app; the 1.0 Studio remains at `/studio`. Without
`PLUSHY_MOCK=1`, generation uses the real SDXL-Turbo backend and
needs the GPU environment described in `GPU_RUNBOOK.md`.

## Testing

```bash
PLUSHY_MOCK=1 python3 -m unittest discover -s tests
```

- Stdlib `unittest` only; no test-runner dependency was added.
- `PLUSHY_MOCK=1` is mandatory for the suites that generate:
  it selects the pipeline's procedural placeholder backend, and
  every job record produced in tests states backend `"mock"`.
  A mock result must never be reported as a real generation.
- Current state: 104 tests (Phase 1: 14, Phase 2: 17, Phase 3:
  20, Phase 4: 16, Phase 5: 18, Phase 6: 19), all passing.
- GPU/SDXL paths, the live FastAPI server, and real-browser UI
  interaction are NOT covered by these suites; docs for each
  phase state plainly what is unverified (notably
  `docs/STUDIO2.md` for the serving path).

## Honesty rules carried through every phase

- Unmeasurable values stay `null`/`unknown` - never estimated
  (asset standards, style values, anchors).
- Unsupported capabilities are recorded as unsupported WITH the
  concrete reason (inpainting in Phase 3; the pixel style
  profile), never faked or silently substituted.
- Missing directions/files are accounted explicitly
  (ok / missing / needs_review), never silently dropped, and
  size mismatches are never silently resized away.
- The backend (mock vs sdxl) is stated in every generation
  record and in the Studio history.
