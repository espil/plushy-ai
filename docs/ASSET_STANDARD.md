# Asset Standard — Phase 1 Analyzer

Implemented in Plushy-AI 2.0 Phase 1 (branch `feature/plushy-ai-2.0`).
Code: `asset_standard/analyze.py`; CLI: `tools/aseprite_analyzer.py`;
tests: `tests/test_asset_standard.py`.

## What it does

`analyze_file(path)` reads one asset file **read-only** and returns the
versioned asset-standard record below. Supported inputs:

- **PNG and other Pillow-readable raster images** — canvas size, Pillow
  color mode, alpha presence, palette (indexed mode), and the content
  bounding box of non-transparent pixels (full canvas when opaque, `null`
  plus a warning when fully transparent).
- **Aseprite `.ase` / `.aseprite`** — parsed with a pure-stdlib parser
  built on the published Aseprite file format: header (canvas, color
  depth, frame count), frame durations, layer chunks (name, file order,
  visibility flag, type, child level, blend mode, opacity when the file
  marks it valid), cel chunks (layer index, x/y position, width/height,
  opacity, z-index, raw/linked/compressed type), and palettes (current
  chunk 0x2019 and legacy chunks 0x0011 / 0x0004).

## Honesty rules (from the 2.0 prompt)

- Chunk types the parser knows but does not extract (tags, slices, user
  data, color profile, tilesets, …) and unknown chunk types are listed in
  `validation.warnings` — never silently skipped.
- Structural corruption (bad magic, truncated header/frame/chunk,
  out-of-range sizes, chunk over-read) raises `AssetAnalysisError`; no
  partial record is produced.
- `anchors`, `directions`, and `style_profile` are always emitted
  empty/`null` in v1: they must come from real Espil reference assets,
  and none exist in this repository yet. Nothing is estimated.
- `content_bounds` is `null` for Aseprite files in v1: the parser records
  cel geometry but does not decode cel pixel data (a warning says so).
- `validation.status` is `"ok"` only when analysis completed with zero
  warnings; otherwise `"needs_review"`.

## The standard record (schema_version "1.0")

```json
{
  "schema_version": "1.0",
  "asset_id": "fixture_char",
  "source": {"filename": "fixture_char.aseprite", "format": "aseprite",
             "size_bytes": 0, "sha256": "…"},
  "canvas": {"width": 16, "height": 16, "color_mode": "RGBA",
             "has_alpha": true},
  "frames": [{"index": 0, "duration_ms": 100,
              "cels": [{"layer_index": 0, "x": 2, "y": 3, "opacity": 255,
                        "type": "compressed", "z_index": 0,
                        "width": 4, "height": 5, "linked_frame": null}]}],
  "layers": [{"index": 0, "name": "Body", "type": "image", "visible": true,
              "child_level": 0, "blend_mode": 0, "opacity": 255}],
  "palette": ["#FF0000FF"],
  "content_bounds": null,
  "anchors": {},
  "directions": [],
  "style_profile": {"pixel_scale": null, "outline": null,
                    "antialiasing": null},
  "validation": {"status": "needs_review", "warnings": ["…"]}
}
```

(Values above are from the synthetic test fixture, not from a real asset.)

Palette entries are `#RRGGBBAA` strings in index order. Layer entries keep
file order; `index` is the layer's position in that order.

## CLI

```bash
python tools/aseprite_analyzer.py path/to/file.aseprite [more files...] \
    [--out DIR]
```

Writes `<asset_id>.asset_standard.json` per input (alongside the input, or
into `--out`), prints a one-line summary plus every warning, and exits 1
if any input failed analysis.

## Not implemented yet (do not read the above as claiming these)

- Cel pixel decoding and Aseprite `content_bounds`.
- Real Espil asset analysis — the repo contains no `.ase/.aseprite`
  files; the parser is verified against a synthetic spec fixture only.
- Aseprite export (Phase 5), reference-image analysis and masks
  (Phase 2), API endpoints (Phase 2+). The prompt's remaining §6 test
  list (mask size match, direction completeness, paper-doll canvas
  checks) belongs to those phases and lands with them.
