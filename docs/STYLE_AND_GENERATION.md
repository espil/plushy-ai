# Style Profiles and Asset Generation - Phase 3

Implemented in Plushy-AI 2.0 Phase 3 (branch `feature/plushy-ai-2.0`).
Code: `generator/` (`profiles.py`, `templates.py`, `generate.py`);
CLI: `tools/asset_generator.py`; tests: `tests/test_generator.py`.

Phase 3 is library + CLI only. It reuses the 1.0 sprite pipeline by
importing `pipeline_sprite` lazily (inside functions), so importing
`generator` never imports torch/diffusers and never loads a model.
No 1.0 file and no Phase 1/2 file was modified.

## What is implemented

- **Text generation** through `pipeline_sprite.SpritePipeline.generate`,
  and **reference-image generation** through its `img2img` (the
  paper-doll "wear" path), driven by a Phase 2 reference record.
- **Variations**: N outputs per job. Per-variation seeds are derived
  deterministically as `seed + i` for variation i, and every seed is
  written into the job record, so a job is reproducible from its
  record alone.
- **Category prompt templates** (`generator/templates.py`): one
  template per Phase 2 category (Hair, Face, Top, Bottom, One-piece,
  Shoes, Armor, Weapon, Accessory, Effects). The template frames the
  user's prompt as a single sprite asset for that slot. The user's
  prompt is preserved verbatim in the job record as `prompt_user`,
  next to the template-composed `prompt_composed`. (pipeline_sprite
  appends its own style suffixes downstream, as it does for all 1.0
  callers.)
- **Generation job record** (schema_version "1.0"), written as
  `<job_id>.job.json` next to the outputs: job id, mode (text /
  img2img), backend, category, user + composed prompts, the negative
  prompt actually used, style profile id, base seed + per-variation
  seeds, size, steps, strength (img2img only), variation count,
  reference id + sha256 when a reference is used, region (see
  gating), the inpainting status record, the Phase 1 asset-standard
  schema version, outputs with filename + seed + size + sha256,
  status, error, and created/finished timestamps.
- **Baseline comparison** (`compare_with_baseline`): measured facts
  only - canvas and content bounds from the Phase 1 analyzer and
  sha256 for the generated output and the baseline image, a
  size-match flag, and an optional side-by-side composite PNG
  (generated left, baseline right). No quality score is computed or
  implied.
- **Output names** are generated safe names (`<job_id>_v<i>.png`);
  user text never appears in a path.

## Style profiles

Profiles are data (`generator/profiles.py`). Each profile manages:
rendering mode, canvas / target output size, palette or color limit,
outline handling, transparent-background policy, resize / sampling
method, post-processing rules, and a `style_profile` block linked to
the Phase 1 asset-standard schema whose measured values
(pixel_scale, outline, antialiasing) stay **null** - no real Espil
reference asset has been analyzed for them, and Phase 3 does not
invent an Espil style profile from nothing. Palette limits are
likewise null: the pipeline neither measures nor enforces one.

| Profile | Rendering mode | Pipeline style | Status |
|---|---|---|---|
| sprite-default | smooth | default | enabled |
| sprite-2.5d | 2.5d | 2.5d | enabled |
| model-3d-look | 3d | 3d | enabled |
| chibi | 3d | chibi | enabled |
| pixel | pixel | (none) | **disabled** - pipeline_sprite has no pixel-art mode: its styles are prompt suffixes on SDXL-Turbo, and there is no pixelation, palette-quantization or nearest-neighbour downscale step in the pipeline |

Enabled profiles map exactly onto the styles pipeline_sprite
implements (`SpriteOptions.style` in default / 2.5d / 3d / chibi).
Selecting a disabled profile is refused with its reason.

## Gating: masks and regions (from Phase 2)

- Text-only generation needs no mask.
- Whole-image img2img over a reference is allowed without a mask;
  the job record states `region: null`.
- A job that claims a target region (`claim_region=True`) must carry
  a Phase 2 mask record whose `generation_target` is present -
  user-confirmed AND non-empty, and belonging to the same reference.
  Missing, unconfirmed, empty, or foreign masks are refused before
  anything is generated.
- Honest limit: a claimed region is validated and **recorded**, but
  generation itself remains whole-image img2img - the pipeline
  cannot restrict an edit to a region. The job record's
  `region.application` says exactly that.

## Inpainting investigation: UNSUPPORTED

Read of `pipeline_sprite.py` (2026-11-17):

- `SpritePipeline` exposes only `generate`, `img2img`,
  `generate_to_file`, and `img2img_to_file`. No method accepts a
  mask; there is no inpaint entry point anywhere in the file.
- `_SDXLSpriteBackend.img2img` loads `AutoPipelineForImage2Image`
  (not an inpainting pipeline) and calls it with prompt, negative
  prompt, image, strength, steps, guidance and generator only -
  no mask argument exists to pass.
- The model is `stabilityai/sdxl-turbo`, a text-to-image / img2img
  model, not an inpainting model.

Conclusion: mask-based region editing / inpainting is **not
supported** by the current pipeline. Phase 3 records this in every
job record (`inpainting: {supported: false, status: "unsupported",
reason: ...}`), refuses explicit inpaint requests, and does NOT
substitute any compositing trick presented as inpainting. Supporting
it later means adding a real inpainting pipeline/model on the 1.0
side or as a new 2.0 backend - a separate decision.

## Mock vs real honesty

`PLUSHY_MOCK=1` selects the pipeline's procedural placeholder
backend. Job records state `backend: "mock"` or `"sdxl"` plainly,
the CLI prints the backend (with an explicit MOCK warning), and a
mock output is never recorded as a model generation. All Phase 3
tests and CLI demonstrations in this environment ran on the mock
backend; the SDXL path is code-identical to the 1.0 call pattern but
was NOT exercised here (no GPU / model weights in this VM).

## CLI

```bash
PLUSHY_MOCK=1 python tools/asset_generator.py "a red hoodie" \
    --category Top --seed 42 --variations 2 --size 256 --out ./gen
PLUSHY_MOCK=1 python tools/asset_generator.py "blue version" \
    --reference ref.png --category Top --out ./gen
python tools/asset_generator.py --list-profiles
```

## NOT implemented (by design, later phases)

- Studio UI wiring of profiles / generation / compare - Phase 6.
- Paper-doll fitting of generated items - Phase 4.
- Aseprite export - Phase 5.
- Inpainting / region-restricted editing - unsupported, see above.
- FastAPI endpoints - none added; `app.py` is untouched.
