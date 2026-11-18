# Aseprite Bridge / Export - Phase 5

Implemented in Plushy-AI 2.0 Phase 5 (branch `feature/plushy-ai-2.0`).
Code: `exporter/` (`aseprite_write.py`, `sheet.py`, `export.py`);
CLI: `tools/export_assets.py`; tests: `tests/test_exporter.py`.
Import side is Phase 1: `asset_standard.analyze_file` reads PNG and
Aseprite files into the versioned asset-standard record (see
`docs/ASSET_STANDARD.md`). This document covers the export side.

## What the export produces

`export_assets()` (and the CLI) package already-generated PNGs into an
export directory:

- **PNG copies** of every input, bytes copied verbatim. PNG export
  works fully independently of the .aseprite export. Originals are
  read-only and never modified.
- **One PNG sprite sheet** when a direction set is given (layout
  below).
- **Optionally one layered `.aseprite`** when named layers are given
  and every layer passes validation.
- **`export_manifest.json`** (schema `1.0`): per-direction and
  per-layer accounting with measured facts (size, alpha, content
  bounds, sha256), output list, validation summary, the .aseprite
  round-trip result, and - when a Phase 1 asset-standard JSON is
  supplied via `source_standard` - that record embedded **in full**
  with its sha256, so a source Aseprite's analyzed metadata is
  preserved through the export path.

## The Aseprite writer (`exporter/aseprite_write.py`)

A minimal but real writer for the published Aseprite file format
(https://www.aseprite.org/docs/files/) - the same spec the Phase 1
parser implements - using only the Python standard library
(`struct` + `zlib`). No Aseprite CLI or other external tool is used
or required.

Supported:

- 32-bit RGBA color depth, **one frame** (duration configurable,
  default 100 ms)
- image layers (type 0), visible + editable, normal blend mode,
  opacity 255, layer names and order exactly as given
- one **compressed-image cel (type 2)** per layer at (0, 0), holding
  the layer's full RGBA pixels, zlib-compressed, row-major,
  top row first
- all layers must share one size, which becomes the canvas; a size
  mismatch or duplicate/empty layer name is refused
  (`AsepriteWriteError`) - nothing is ever resized

NOT written (absent from the file, not faked):

- multiple frames / animation
- layer groups, tilemap layers, linked cels
- tags, slices, user data, external files, paths, masks (deprecated)
- palettes and color profiles (meaningless for direct RGBA cels)
- cel-extra and tileset chunks

## Round-trip evidence (the verification that exists here)

ASE export is claimed **only** because the writer's output is proven
by round-trip:

1. Unit tests (`tests/test_exporter.py`, 18 tests) write layered
   .aseprite files from known PNGs and re-analyze them with the
   Phase 1 analyzer, asserting: layer names and order, canvas size,
   frame count = 1, one compressed cel per layer with the expected
   geometry. A byte-level test also zlib-decompresses a written cel
   and checks the exact RGBA pixel values.
2. The export itself re-analyzes every .aseprite it writes and puts
   the result in the manifest (`outputs.aseprite.roundtrip`); if the
   round-trip fails, the .aseprite is marked `needs_review` with the
   reason instead of `ok`.
3. Independent CLI check (run 2026-11-17 on a synthetic fixture set):
   `tools/export_assets.py` exported 8 directions + 2 layers to
   `hero.aseprite`, then the separate Phase 1 CLI
   `tools/aseprite_analyzer.py hero.aseprite` read it back as
   16x12 RGBA, 1 frame, layers `Body`, `Hair` (both visible), 2
   compressed cels of 16x12 at (0, 0). (The analyzer reports
   `needs_review` for every Aseprite file because v1 does not decode
   cel pixels, so `content_bounds` stays null - a known Phase 1
   limit, not a defect in the written file.)

**Honest boundary:** whether the real Aseprite application opens
these files is **unverified** - Aseprite is not installed in this
environment. The Phase 1 parser round-trip and the byte-level format
checks are the verification available here; the writer follows the
published spec exactly (header, frame, layer and cel layouts are the
same layouts the Phase 1 synthetic fixture uses).

## Sprite sheet layout

Fixed grid, documented in `exporter/sheet.py`:

- 4 columns x 2 rows, cell = the shared canvas size, sheet size =
  (4 x canvas width) x (2 x canvas height)
- directions in canonical order (S, SE, E, NE, N, NW, W, SW),
  left-to-right, top row first:

```
S   SE  E   NE
N   NW  W   SW
```

- a missing or invalid direction keeps its cell fully transparent;
  cells are never collapsed and no direction shifts into another's
  cell. The manifest records each direction's cell coordinates and
  whether it was packed.

## Pre-export validation rules

Measured with the Phase 1 analyzer (`asset_standard.analyze_file`),
mirroring Phase 4's accounting style:

- **Direction completeness:** when a direction set is exported, all
  8 directions are always listed - `ok`, `missing`, or
  `needs_review` (naming the facts). A layer-only export lists no
  directions and claims none.
- **Canvas size consistency:** the expected canvas is the first
  present direction's size (canonical order) or the first layer's
  size; any other size is a `size mismatch` - the item is marked
  `needs_review`, excluded from the sheet, and blocks the .aseprite.
  Nothing is resized to fit.
- **Transparency / alpha:** an image with no alpha channel, or one
  that is fully transparent (null content bounds), is marked
  `needs_review` with the reason.
- **Layer completeness:** duplicate layer handling is refused by
  the writer; a layer that fails validation blocks the .aseprite
  (status `needs_review` with the offending layer names) while its
  PNG copy and the rest of the export still complete.
- The export's overall `status` is `ok` only when every accounted
  item is `ok`; the CLI exits 1 on `needs_review` so scripts can
  gate on a clean export.

## CLI

```bash
# per-direction set (any subset; missing directions are reported)
python tools/export_assets.py --out ./export \
    --direction S=south.png --direction SE=se.png ...

# named layers + layered .aseprite + source metadata preservation
python tools/export_assets.py --out ./export \
    --layer Body=body.png --layer Hair=hair.png \
    --aseprite character.aseprite \
    --source-standard src.asset_standard.json
```

## Not implemented / not verified

- No FastAPI or Studio UI wiring (Phase 6); `app.py` is untouched.
- No Aseprite CLI adapter (deliberately: the writer needs no
  external tool, and no CLI exists in this environment to adapt).
- Real-Aseprite opening of written files: unverified (see above).
- Multi-frame / animated export, groups, tags, slices, palettes:
  not written (listed above); a future writer extension, not a
  hidden gap.
- Source Aseprite metadata is preserved by embedding the Phase 1
  record in the export manifest; it is NOT re-encoded into the
  written .aseprite (the writer emits layers/cels only), so an
  export .aseprite does not carry the source file's tags or palette.
