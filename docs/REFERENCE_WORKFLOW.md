# Reference Workflow — Phase 2 Reference Analyzer and Region Selection

Implemented in Plushy-AI 2.0 Phase 2 (branch `feature/plushy-ai-2.0`).
Code: `reference/` (`upload.py`, `analyze.py`, `mask.py`);
CLI: `tools/reference_analyzer.py`; tests: `tests/test_reference.py`.

Phase 2 is a **library plus CLI only**. The 1.0 files are untouched:
nothing here is imported by `app.py`, and no existing file was modified.

## What is implemented

### Upload validation (`reference/upload.py`)

Every reference image (PNG / JPG / WEBP) must pass all four checks —
extension alone is never trusted:

1. **Size**: at most `DEFAULT_MAX_BYTES` (20 MB, mirroring the 1.0
   server's upload cap; callers may pass a smaller limit).
2. **Extension**: one of `.png`, `.jpg`, `.jpeg`, `.webp`.
3. **Magic bytes**: PNG signature, JPEG SOI, or RIFF/WEBP header must
   match the extension's format.
4. **Decoder verification**: Pillow must decode the bytes and report
   the same format. Any mismatch raises `ReferenceError`.

### Safe server-side filenames

Stored files are named only from a generated ID
(`ref_<uuid4 hex>`) plus a canonical extension taken from the
*detected* format (`.png` / `.jpg` / `.webp`). The user-supplied
filename is preserved solely as metadata (`source.original_filename`)
and never appears in any path; ingestion also asserts the resolved
destination stays inside the storage directory. Path traversal names
such as `../../evil.png` therefore produce a normal safe stored file.

### Reference analysis (`reference/analyze.py`)

`ingest_reference(data, original_filename, storage_dir, category=...)`
validates, stores, and analyzes an upload. `analyze_reference(path)`
does the same validation and analysis for an existing on-disk file
without copying it. Analysis **reuses the Phase 1 Asset Standard
Engine** (`asset_standard.analyze_file`, imported — not duplicated).

The reference record (schema `1.0`) preserves the link between the
analysis and the original image:

```json
{
  "schema_version": "1.0",
  "reference_id": "ref_<uuid4 hex>",
  "source": {"original_filename": "hero.png",
             "stored_filename": "ref_<...>.png",
             "format": "PNG", "size_bytes": 0, "sha256": "..."},
  "category": "Top",
  "asset_standard": { "... the full Phase 1 record ..." },
  "analysis_asset_id": "...", "analysis_sha256": "...",
  "mask": null, "generation_target": null
}
```

Ingestion also writes `<reference_id>.reference.json` next to the
stored image. Originals are read-only and never modified.

### Category selection

Exactly this set is accepted (anything else raises `ReferenceError`):
Hair, Face, Top, Bottom, One-piece, Shoes, Armor, Weapon, Accessory,
Effects. Category is optional at ingestion (may be chosen later) but is
validated whenever one is supplied.

### Masks (`reference/mask.py`)

**Convention**: a mask is the exact size of its reference image. Saved
as a transparent PNG, mask-area pixels are opaque white
(255, 255, 255, 255) and all other pixels are fully transparent
(0, 0, 0, 0). On load, alpha > 0 means "in the mask".

Library operations:

- `MaskCanvas(width, height)` — create an empty mask.
- `add_rectangle(x, y, w, h)` / `remove_rectangle(...)` — user edit
  operations (rectangles must lie fully inside the mask).
  `clear()`, `bounds()`, `pixel_count()`, `is_empty()` for queries.
- `validate_size(w, h)` — raises unless the mask exactly matches the
  reference image size; enforced by `build_mask_record` and
  `save_mask` before anything is written.
- `suggest_mask(reference_record)` — proposes a mask from the Phase 1
  analysis `content_bounds` (the non-transparent content box). **This
  is a suggestion only.**
- `save_mask(mask, path, reference_record, confirmed=...)` — writes
  the transparent PNG plus a metadata JSON (same name, `.json`
  suffix) linking reference ID, category, `confirmed` flag, mask
  sha256, reference sha256, bounds, and pixel count.
- `load_mask(path, expected_size=...)` — reads a mask back.

**No mask = no generation target.** A mask record's
`generation_target` is `None` unless the mask is both user-confirmed
(`confirmed=True`) and non-empty. Suggestions are unconfirmed by
construction, and a fresh reference record has `mask: null` and
`generation_target: null`. `generation_target(mask_record)` is the
single gate Phase 3 must call before generating anything.

## CLI

```bash
python tools/reference_analyzer.py path/to/ref.png [--category Hair] \
    [--out ./refs] [--suggest-mask]
```

Ingests each file into the storage directory (default `./references`)
and prints the stored safe name, format, canvas size, sha256 prefix,
and category. `--suggest-mask` additionally writes
`<reference_id>.suggested_mask.png` (+ `.json`) with
`confirmed: false`. Exit code is 1 if any input fails validation.

## What is NOT implemented (honest limits)

- **No Studio UI mask editor.** Adding/removing mask regions in a
  browser UI is Phase 6. Phase 2 provides the library operations
  (create / add rectangle / remove rectangle / save / load) that the
  UI will call; rectangle edits are the finest granularity provided —
  there is no brush tool yet.
- **No generation.** Creating assets from a confirmed mask is Phase 3.
  Nothing in this package calls `pipeline_sprite.py` or any model.
- **No server/API wiring.** No FastAPI route exists for references;
  `app.py` is unchanged (separation rule). A future phase must add
  routes that call this library and enforce authentication and the
  same validation server-side.
- **Suggestion quality is deliberately minimal.** The suggested mask
  is the axis-aligned bounding box of non-transparent content from the
  Phase 1 analysis. It is not segmentation: opaque-background images
  yield a full-canvas suggestion, and fully transparent images yield
  an empty one. It exists so a user has something to edit, never as
  an automatic target.
- **Mask PNG round-trip is binary.** Semi-transparent mask edges are
  collapsed to in/out (alpha > 0) on load; feathered masks are not
  represented in v1.
- **In-memory pixel count.** `pixel_count()` iterates pixels in
  Python; fine for asset-sized images, not optimized for very large
  canvases.

## Security rules applied

- Size limit, extension allow-list, magic-byte check, and decoder
  verification on every upload — all four, every time.
- Generated safe IDs for all stored names; user filenames are metadata
  only; resolved-path containment is asserted at write time.
- Category allow-list validation.
- Originals opened read-only; analysis reuses the Phase 1 read-only
  analyzer.
