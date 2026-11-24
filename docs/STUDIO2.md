# Studio 2.0 - Phase 6 (Studio UI + API wiring)

Phase 6 wires the Phase 1-5 libraries into a working Studio,
WITHOUT modifying any 1.0 or Phase 1-5 file. Han's separation rule
overrides the prompt's "extend static/studio.html and the API"
mechanism: instead of editing `static/studio.html` or `app.py`,
Phase 6 adds a new page, a new service layer, a new router, and a
new standalone entrypoint that mounts everything onto the
unmodified 1.0 app.

## Pieces (all new files)

| File | Role |
|---|---|
| `studio2/service.py` | Framework-free service layer over the Phase 1-5 libraries + in-memory job registry. Imports no web framework; fully testable without FastAPI. |
| `studio2/router.py` | Thin FastAPI router: the ONLY Phase 6 module that requires FastAPI, imported only when serving. Pure adapter over the service (Studio2Error -> HTTP status + plain-text detail). |
| `studio2_server.py` | Standalone entrypoint: imports the 1.0 `app.app`, includes the 2.0 router, serves the new page at `/studio2`. |
| `static/studio2.html` | The 9-screen Studio 2.0 page (vanilla JS, no build step, no external/CDN resources). Calls ONLY the 2.0 endpoints. |
| `tests/test_studio2.py` | Service-layer + static-HTML tests (stdlib unittest, PLUSHY_MOCK=1, no FastAPI). |

## How to run

```bash
# On the GPU PC / in Docker, where the 1.0 app already runs:
PLUSHY_MOCK=1 python3 studio2_server.py     # mock placeholders, no GPU
python3 studio2_server.py                   # real SDXL backend
# then open http://localhost:8000/studio2
```

Environment: `PLUSHY_STUDIO2_DIR` = where the service stores its
files (default `<repo>/studio2_data`: references/, masks/,
generated/, compares/, fits/, exports/, assets/);
`PLUSHY_STUDIO2_PORT` = port (default 8000).

The 1.0 Studio stays at `/studio`; every 1.0 endpoint keeps its
exact behaviour. The service layer can also be used without any
server:

```python
from studio2 import Studio2Service
svc = Studio2Service("studio2_data")
```

## The 9 screens (static/studio2.html)

1. **Input** (`screen-input`) - reference upload (Phase 2 validated
   ingestion) + original preview + the full reference record.
2. **Category** (`screen-category`) - the Phase 2 category set,
   loaded from the service bootstrap.
3. **Region** (`screen-region`) - canvas mask editor: drag to add /
   remove rectangles (the Phase 2 rectangle model); "Load suggested
   mask" fetches the Phase 2 suggestion as a PROPOSAL - it is drawn
   unconfirmed and only becomes the generation target after the
   user checks the confirm box and saves.
4. **Reference Standard** (`screen-standard`) - asset analysis via
   the Phase 1 engine + style profile select from
   `generator.profiles`; disabled profiles render as disabled
   options WITH their reason (e.g. pixel).
5. **Generate** (`screen-generate`) - prompt, negative prompt,
   seed, variations, size, steps, img2img strength, and the
   "target the confirmed mask region" claim toggle. Polls
   `/api/jobs/{job_id}` until a terminal status; mock results are
   labelled MOCK in the status line.
6. **Compare** (`screen-compare`) - generated vs baseline
   side-by-side composite + the measured facts record
   (`generator.compare_with_baseline`); no quality score exists.
7. **Paper Doll Preview** (`screen-paperdoll`) - fits the last
   generation output onto the uploaded reference body for one slot
   (Phase 4); the manifest accounts for all 8 directions - the
   seven without a body are honestly "missing".
8. **Export** (`screen-export`) - PNG copies / sprite sheet /
   layered .aseprite from a generation job or a fit (Phase 5),
   with the manifest's validation states shown and download links.
9. **History** (`screen-history`) - every registry job with its
   parameters, status (queued / processing / completed / failed /
   cancelled), backend (mock labelled), and error text.

All server text is rendered with `textContent` / DOM APIs - the
page contains no `innerHTML` at all (asserted by the tests).

## Endpoints

The prompt's proposed API (section 5), implemented in
`studio2/router.py` over the service layer:

| Method + path | Delegates to | Notes |
|---|---|---|
| `POST /api/assets/analyze` | `asset_standard.analyze_file` via the service | multipart file; stored under a generated safe name |
| `GET /api/assets/{asset_id}` | service asset store | 404 for unknown ids |
| `POST /api/reference/analyze` | `reference.ingest_reference` | multipart file + optional category; Phase 2 validation (size / extension / content) |
| `POST /api/masks` | `reference.save_mask` / `suggest_mask` | JSON: rectangles + base + confirmed; `{"suggest_only": true}` returns the unconfirmed suggestion |
| `POST /api/assets/generate` | `generator.run_generation` via the job registry | 202 + job view; the router runs the job as a background task; invalid requests (bad category, disabled profile, unconfirmed region claim, inpainting) are refused with 400 BEFORE queueing |
| `GET /api/jobs/{job_id}` | job registry | 1.0-shaped status: status / progress / message / result / error / elapsed_sec, plus params + backend |
| `POST /api/paperdoll/compose` | `fitting.fit_layers` | body/layer as `{reference_id}` or `{job_id, filename}`; generation linkage proven by sha256 |
| `POST /api/export` | `exporter.export_assets` | `source_type`: `generation` (outputs as layers) or `fitting` (direction composites + sheet); optional layered .aseprite |

Support endpoints the page needs around those:

| Method + path | Purpose |
|---|---|
| `GET /api/studio2/bootstrap` | categories + style profiles (disabled ones with reasons) + inpainting verdict + layer slots |
| `GET /api/jobs` | history list, newest first |
| `DELETE /api/jobs/{job_id}` | cancel a QUEUED job (mirrors the role of the 1.0 `DELETE /api/job/{job_id}`) |
| `POST /api/compare` | generated vs baseline facts + side-by-side PNG |
| `GET /api/studio2/files?path=` | read-only preview/download of service files; the path must resolve inside the service data root (traversal refused, 404) |

The 1.0 `/api/status/{job_id}` and `/api/result/{job_id}` are
untouched and unshadowed.

## Job registry

In-memory, mirroring the 1.0 job shape so the UI polls long GPU
jobs the same way: `job_id` (`sjob_...`), `kind`, `status`
(queued / processing / completed / failed / cancelled),
`progress`, `message`, `result`, `error`, `elapsed_sec`, plus the
request `params` and the Phase 3 `backend` for history honesty.
Generation executes when `run_generation_job` is called (the
router schedules it as a FastAPI background task after returning
202); failures land as status `failed` with the error recorded,
never as a raised exception past the registry. Registry state is
per-process and is lost on restart; the files under the service
root are not.

## Security (prompt section 6)

- Uploads reuse the Phase 2 validation verbatim (size limit,
  extension AND magic/Pillow content check) - no reimplementation.
- User filenames are never used as paths: uploads land under
  generated safe IDs; every other file name is service-generated.
- The file endpoint resolves paths inside the service root only.
- Errors shown to the UI are plain text from this codebase / the
  Phase 1-5 libraries, rendered with `textContent`.
- No secrets or tokens anywhere in the Phase 6 files.

## Web-drive output saving (added 2026-11-24, Han's directive)

From 2.0 on, outputs are saved to a web drive, not only to the
local disk. `studio2/webdrive.py` mirrors output trees into the
folder named by `PLUSHY_WEBDRIVE_DIR` - point it at the
desktop-sync folder of a web drive (Google Drive, OneDrive, ...)
and the drive client uploads from there. No cloud credentials
are stored and no network code runs in this repo.

- The mirror is incremental (size + mtime), idempotent, and
  writes `webdrive_manifest.json` into the target root.
- `Studio2Service.sync_to_webdrive()` mirrors the whole 2.0 data
  root; every export also syncs best-effort and carries the
  report in its result under `webdrive`. A drive failure never
  fails an export.
- `python3 -m studio2.webdrive` mirrors the default trees (2.0
  data root + 1.0 `outputs/`) for batch/runner use and prints a
  JSON report.
- With `PLUSHY_WEBDRIVE_DIR` unset, saving is disabled and every
  entry point reports `{"status": "disabled"}` honestly.
- Covered by `tests/test_webdrive.py`; the full suite passes
  under `PLUSHY_MOCK=1` (113 tests). The mirror mechanism is
  verified; an end-to-end upload by a real drive client is the
  PC-side check that remains.

## Verified vs unverified

Verified in the development VM (no GPU, no FastAPI):

- Full service-layer flow end to end under `PLUSHY_MOCK=1`:
  upload -> analyze -> mask suggest + confirm -> generation job
  (queued -> completed, seeds derived, region recorded) -> status
  poll -> compare (side-by-side written) -> fit (S ok, 7 missing,
  sha256 linkage) -> export (generation: manifest ok + ASE
  round-trip ok; fitting: sheet written, 7 missing honestly
  counted) -> history. See `tests/test_studio2.py` (19 tests;
  full suite 104/104).
- Refusals: bad category, disabled profile (pixel), region claim
  without / with an unconfirmed mask, inpaint request, corrupt or
  mislabeled upload, out-of-bounds mask rectangle, unknown
  job/asset ids, file-path traversal.
- The page: balanced tags (html.parser), all 9 screen sections,
  every `getElementById` target present, fetch calls target only
  the 2.0 endpoints, no `innerHTML`, no external resources.

UNVERIFIED here:

- **Live server run**: FastAPI is not installed in this VM, so
  `studio2_server.py` and `studio2/router.py` were never executed
  (the router imports cleanly only where FastAPI exists; the
  package and service import without it, which the tests prove).
  Verify on the GPU PC / Docker, where the 1.0 app already runs.
- **Real browser interaction** with the page (canvas mask editing,
  polling, previews) - the page was checked statically only.
- **The SDXL/GPU generation path** through the new endpoints -
  all Phase 6 generation evidence is the mock backend, labelled
  "mock" in every record and in the UI.
