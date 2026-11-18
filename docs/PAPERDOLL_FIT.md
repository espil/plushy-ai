# Paper Doll Integration - Phase 4 Fitting

Implemented in Plushy-AI 2.0 Phase 4 (branch `feature/plushy-ai-2.0`).
Code: `fitting/fit.py`; CLI: `tools/paperdoll_fit.py`;
tests: `tests/test_paperdoll_fit.py`.

## What it is

Phase 4 fits generated or hand-made item layers onto blank-body
sprites and records the result in a versioned manifest. It is a
2.0-side companion to the 1.0 `paperdoll.py`: per Han's separation
rule it does NOT edit `paperdoll.py`. It reuses 1.0 by importing it
(`paperdoll.load_prompts`, `paperdoll.extract_layer`, and
paperdoll's documented compose layer order) and reuses the Phase 1
analyzer for measured content bounds and Phase 3 generation job
records for provenance.

## The headline difference from 1.0 compose

1.0 `paperdoll.py compose` silently resizes any layer whose size
differs from the body canvas:

```python
if layer.size != canvas.size:
    layer = layer.resize(canvas.size)
```

Phase 4 VALIDATES instead. A size mismatch marks the direction
`needs_review` in the manifest, records the body size and the layer
size side by side, and produces NO composite and NO resized copy.
Fitting never happens by quietly changing the asset.

## Conventions kept from 1.0

- Direction order is exactly `S, SE, E, NE, N, NW, W, SW`.
- Compose order is paperdoll's documented order:
  `hair_back, body, bottoms, tops, shoes, face, hair_front`
  (hair_back goes UNDER the body; the rest layer over it).
- Body discovery follows paperdoll's naming: a `_<DIR>_` or
  trailing `_<DIR>` token in the stem (`body_S_s0.png`,
  `layer_S_p0_s0.png`), or a `p{NN}_` prefix mapped through a
  caller-supplied directions list by prompt index, as in
  `paperdoll.py batch --directions`.
- `--body-pattern` mirrors batch's glob filter (e.g. `*_s0.png`).
- Outputs follow the batch naming family: per-layer copies
  `layer_{DIR}_{slot}.png` and composites `worn_{DIR}.png`
  (batch's `layer_{DIR}_p{pi}_s{seed}.png` / `worn_{DIR}_...` minus
  the prompt/seed tags, which a fit does not have).

## Direction accounting

All 8 directions appear in every manifest, always. Each entry is
one of:

- `ok` - body and every supplied layer present, sizes validated,
  layer copies and composite written.
- `missing` - body or a supplied layer is absent for that
  direction; the `missing` list names the side (`body`,
  `layer:tops`, ...). Never a silent skip.
- `needs_review` - a layer canvas size differs from the body
  canvas; nothing composed, nothing resized.

## Alignment evidence - measured, not claimed

For each fitted direction the manifest records the Phase 1
analyzer's `content_bounds` for the body and for each layer, side
by side, under `validation.alignment`. That is the alignment
evidence. No stronger alignment claim is made: equal bounds are
not required and offset correction is not performed.

## Anchors - honestly null

`anchors` is null in the manifest and in every entry. No anchor or
fitting-coordinate data exists in the baseline body/item assets,
and no coordinate is guessed or fixed. Composition is
same-canvas overlay only - the existing paperdoll model, in which
layers share the body canvas. If real anchor data is ever measured
from baseline assets or game data, it belongs in a later phase.

## Generation linkage (Phase 3)

A fit may link one layer slot to a Phase 3 generation job record
(`--generation-record` + `--generation-slot`). The link is proven
by content: the layer file's sha256 must match a recorded output
sha256 in the job record, or the fit is refused. The manifest then
records `generation: {job_id, slot, output_filename,
output_sha256, backend}` - the backend string is copied from the
job record, so a mock generation stays labelled mock. A plain
layer PNG without a generation record is equally supported and
records `generation: null`.

## Manifest shape (schema_version "1.0")

```json
{
  "schema_version": "1.0",
  "fit_id": "fit_...",
  "created_at": "...",
  "composition_model": "same_canvas_overlay",
  "compose_order": ["hair_back", "body", "bottoms", "tops",
                    "shoes", "face", "hair_front"],
  "directions_order": ["S", "SE", "E", "NE", "N", "NW", "W", "SW"],
  "anchors": null,
  "anchors_note": "...",
  "generation": null,
  "layers_spec": [{"slot": "tops", "name": "red-hoodie",
                   "source_file": "hoodie.png"}],
  "entries": [
    {"direction": "S", "status": "ok", "missing": [],
     "body": {"filename": "body_S_s0.png", "sha256": "..."},
     "layers": [{"slot": "tops", "name": "red-hoodie",
                 "filename": "hoodie.png", "sha256": "...",
                 "size": {"width": 16, "height": 16},
                 "compose_index": 3}],
     "validation": {"size_match": true,
                    "body_size": {"width": 16, "height": 16},
                    "alignment": {"body_content_bounds": {},
                                  "layers": {"tops": {}}},
                    "status": "ok"},
     "anchors": null,
     "outputs": {"layers": {"tops": {"filename": "layer_S_tops.png",
                                     "sha256": "..."}},
                 "composite": {"filename": "worn_S.png",
                               "sha256": "..."}},
     "notes": []}
  ],
  "summary": {"ok": 8, "missing": 0, "needs_review": 0}
}
```

## CLI

```bash
PLUSHY_MOCK=1 python tools/paperdoll_fit.py \
    --body-dir ./paperdoll/bodies/female \
    --layer tops=./layers/hoodie.png \
    --layer hair_front=./layers/hair_dir \
    --out ./paperdoll/fit/char01

PLUSHY_MOCK=1 python tools/paperdoll_fit.py \
    --body body_S_s0.png --direction S \
    --layer tops=gen_v0.png \
    --generation-record gen.job.json --generation-slot tops \
    --out ./out
```

Each `--layer` is `SLOT=PATH` (repeatable); PATH is one PNG (used
for the direction its filename names, or every direction if it
names none) or a directory of per-direction PNGs. Slots:
hair_back, bottoms, tops, shoes, face, hair_front. The CLI prints
one status line per direction, the generation link, and the
summary; it exits 1 on invalid requests (unknown slot, unprovable
generation link, missing layer file).

## Also exposed

`fitting.extract_layer(worn, body, thresh=28)` delegates to
`paperdoll.extract_layer` with paperdoll's own threshold parameter
- the diff-based layer extraction is reused, not reimplemented.
`fitting.load_prompts` likewise delegates to
`paperdoll.load_prompts`.

## What is NOT done

- No Studio UI preview (Phase 6) and no server/API wiring;
  `app.py` is untouched.
- No Aseprite export (Phase 5).
- No anchor invention, no offset correction, no resizing -
  by design, see above.
- No generation: fitting consumes Phase 3 outputs (or plain
  PNGs); it never calls the sprite pipeline itself. The only
  pipeline-adjacent reuse is `paperdoll.extract_layer`, which is
  pure image diffing.
- Duplicate body files for one direction: the first sorted file
  wins (paperdoll batch processes every match; a fit needs one
  body per direction). Duplicates are not listed in the manifest
  in v1 - a known gap, recorded here rather than hidden.
