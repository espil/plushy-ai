"""Asset generation jobs (Phase 3).

Reuses the 1.0 sprite pipeline by importing `pipeline_sprite` LAZILY
(inside functions only): importing this package never imports torch /
diffusers and never loads a model. The pipeline is constructed once
per job, exactly like 1.0 code constructs `SpritePipeline()`.

Backend honesty: `pipeline_sprite.MOCK` (PLUSHY_MOCK=1) selects the
procedural placeholder backend. Every job record states its backend
plainly ("mock" or "sdxl"); a mock result is a placeholder and the
record never presents it as a real model generation.

Gating (Phase 2 -> Phase 3):
  - Text-only generation needs no mask.
  - Whole-image img2img over a reference (no region claimed) is
    allowed without a mask; the job record states region: None.
  - A job that CLAIMS to edit a target region of a reference must
    carry a mask record whose Phase 2 `generation_target` is not None
    (user-confirmed AND non-empty). Otherwise the job is refused
    before anything is generated.

Inpainting: investigated and UNSUPPORTED - see INPAINTING_STATUS and
docs/STYLE_AND_GENERATION.md. Nothing in this module fakes it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from asset_standard import SCHEMA_VERSION as ASSET_STANDARD_SCHEMA_VERSION
from asset_standard import analyze_file
from reference.mask import generation_target
from reference.upload import validate_category

from .profiles import GeneratorError, get_profile
from .templates import compose_prompt

JOB_SCHEMA_VERSION = "1.0"
COMPARE_SCHEMA_VERSION = "1.0"

# Evidence (pipeline_sprite.py, read 2026-11-17): SpritePipeline
# exposes generate / img2img / generate_to_file / img2img_to_file and
# nothing else; neither backend accepts a mask argument -
# _SDXLSpriteBackend.img2img builds an AutoPipelineForImage2Image
# call with prompt/image/strength only, and SDXL-Turbo is not an
# inpainting model. There is no supported mask-based editing path.
INPAINTING_STATUS = {
    "supported": False,
    "status": "unsupported",
    "reason": "pipeline_sprite.SpritePipeline has no mask or inpaint "
              "entry point: generate() and img2img() accept no mask, "
              "the SDXL backend's img2img uses "
              "AutoPipelineForImage2Image with prompt/image/strength "
              "only, and stabilityai/sdxl-turbo is not an inpainting "
              "model. No compositing trick is substituted for real "
              "inpainting.",
}


def inpainting_status() -> dict:
    """Return the (unsupported) inpainting status record."""
    return dict(INPAINTING_STATUS)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_job_id() -> str:
    """Generate a safe server-side job ID (no user input)."""
    return "gen_" + uuid.uuid4().hex


def derive_seed(base_seed: int, variation_index: int) -> int:
    """Per-variation seed: base_seed + variation_index.

    Deterministic and documented: variation i of a job always uses
    seed (base_seed + i), so a job is reproducible from its record.
    """
    if variation_index < 0:
        raise GeneratorError("variation index must be >= 0")
    return int(base_seed) + int(variation_index)


def backend_name() -> str:
    """Return "mock" or "sdxl" for the pipeline's selected backend.

    Imports pipeline_sprite lazily; reads its MOCK flag only - this
    does not load any model.
    """
    import pipeline_sprite

    return "mock" if pipeline_sprite.MOCK else "sdxl"


def _load_pipeline():
    import pipeline_sprite

    return pipeline_sprite


def run_generation(prompt, out_dir, category=None, profile_id="sprite-default",
                   seed=0, variations=1, width=None, height=None, steps=6,
                   negative_prompt=None, reference_record=None,
                   reference_image_path=None, strength=0.6,
                   claim_region=False, mask_record=None, inpaint=False,
                   job_id=None) -> dict:
    """Run one generation job and return its versioned job record.

    The record is also written to `<out_dir>/<job_id>.job.json`.
    Output PNGs are named `<job_id>_v<i>.png` (generated safe names).
    Raises GeneratorError for invalid requests, disabled profiles,
    gating refusals, and inpaint requests; pipeline failures are
    recorded (status "failed") in the written record and re-raised as
    GeneratorError.
    """
    if inpaint:
        raise GeneratorError(
            "inpainting requested but unsupported: "
            + INPAINTING_STATUS["reason"])
    if not prompt or not str(prompt).strip():
        raise GeneratorError("prompt must not be empty")
    if variations < 1:
        raise GeneratorError("variations must be >= 1")
    if steps < 1:
        raise GeneratorError("steps must be >= 1")

    profile = get_profile(profile_id)
    if not profile["enabled"]:
        raise GeneratorError(
            f"style profile {profile_id!r} is disabled: "
            + str(profile["disabled_reason"]))
    if category is not None:
        validate_category(category)

    mode = "img2img" if reference_record is not None else "text"
    if mode == "img2img" and reference_image_path is None:
        raise GeneratorError(
            "reference-based generation needs reference_image_path")

    # -- gating ---------------------------------------------------------
    region = None
    if claim_region:
        if mode != "img2img":
            raise GeneratorError(
                "a target region can only be claimed for "
                "reference-based generation")
        target = generation_target(mask_record)
        if target is None:
            raise GeneratorError(
                "region-targeted generation refused: no confirmed, "
                "non-empty mask generation_target (Phase 2 gate)")
        if target["reference_id"] != reference_record["reference_id"]:
            raise GeneratorError(
                "mask record does not belong to this reference")
        # Honesty: the target is validated and recorded, but the
        # pipeline cannot restrict editing to the region (that would
        # be inpainting - unsupported). Generation stays whole-image
        # img2img; the record says so instead of implying otherwise.
        region = dict(target)
        region["application"] = (
            "recorded_target_only: generation is whole-image img2img; "
            "region-restricted editing is unsupported (see inpainting)")

    target_size = profile["target_size"]
    out_w = int(width) if width else int(target_size["width"])
    out_h = int(height) if height else int(target_size["height"])
    if out_w <= 0 or out_h <= 0:
        raise GeneratorError("output size must be positive")

    composed = compose_prompt(category, prompt) if category else prompt
    jid = job_id or generate_job_id()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    record = {
        "schema_version": JOB_SCHEMA_VERSION,
        "job_id": jid,
        "status": "running",
        "mode": mode,
        "backend": backend_name(),
        "category": category,
        "prompt_user": prompt,
        "prompt_composed": composed,
        "negative_prompt": negative_prompt,
        "style_profile_id": profile_id,
        "rendering_mode": profile["rendering_mode"],
        "pipeline_style": profile["pipeline_style"],
        "seed": int(seed),
        "seeds": [derive_seed(seed, i) for i in range(variations)],
        "size": {"width": out_w, "height": out_h},
        "steps": int(steps),
        "strength": float(strength) if mode == "img2img" else None,
        "variations": int(variations),
        "reference": None,
        "region": region,
        "inpainting": inpainting_status(),
        "asset_standard_schema_version": ASSET_STANDARD_SCHEMA_VERSION,
        "outputs": [],
        "error": None,
        "created_at": _now(),
        "finished_at": None,
    }
    if mode == "img2img":
        record["reference"] = {
            "reference_id": reference_record["reference_id"],
            "sha256": reference_record.get("source", {}).get("sha256"),
            "category": reference_record.get("category"),
        }

    job_path = out / f"{jid}.job.json"

    def _write():
        job_path.write_text(json.dumps(record, indent=2, ensure_ascii=False),
                            encoding="utf-8")

    try:
        pipeline_sprite = _load_pipeline()
        pipe = pipeline_sprite.SpritePipeline()
        init_image = None
        if mode == "img2img":
            from PIL import Image

            with Image.open(reference_image_path) as im:
                init_image = im.convert("RGBA").copy()
        for i in range(variations):
            v_seed = derive_seed(seed, i)
            opts = pipeline_sprite.SpriteOptions(
                prompt=composed,
                seed=v_seed,
                width=out_w,
                height=out_h,
                num_inference_steps=int(steps),
                style=profile["pipeline_style"],
            )
            if negative_prompt is not None:
                opts.negative_prompt = negative_prompt
            if record["negative_prompt"] is None:
                record["negative_prompt"] = opts.negative_prompt
            dest = out / f"{jid}_v{i}.png"
            if mode == "img2img":
                pipe.img2img_to_file(composed, init_image, dest,
                                     strength=float(strength), opts=opts)
            else:
                pipe.generate_to_file(composed, dest, opts=opts)
            data = dest.read_bytes()
            record["outputs"].append({
                "filename": dest.name,
                "seed": v_seed,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            })
    except GeneratorError:
        raise
    except Exception as e:  # noqa: BLE001 - recorded, then surfaced
        record["status"] = "failed"
        record["error"] = f"{type(e).__name__}: {e}"
        record["finished_at"] = _now()
        _write()
        raise GeneratorError(
            f"generation failed (job {jid}): {record['error']}") from e

    record["status"] = "completed"
    record["finished_at"] = _now()
    _write()
    record["job_filename"] = job_path.name
    return record


def compare_with_baseline(generated_path, baseline_path, out_dir=None) -> dict:
    """Compare a generated output with a baseline body/item image.

    Measured facts only (Phase 1 analysis: canvas, content bounds,
    sha256) - no subjective quality scoring. When `out_dir` is given,
    a side-by-side composite PNG (generated left, baseline right, on a
    transparent canvas) is written there and recorded.
    """
    generated_path = Path(generated_path)
    baseline_path = Path(baseline_path)
    gen_std = analyze_file(generated_path)
    base_std = analyze_file(baseline_path)

    def _facts(path, std):
        return {
            "filename": path.name,
            "sha256": std.get("source", {}).get("sha256"),
            "canvas": std.get("canvas"),
            "content_bounds": std.get("content_bounds"),
        }

    record = {
        "schema_version": COMPARE_SCHEMA_VERSION,
        "generated": _facts(generated_path, gen_std),
        "baseline": _facts(baseline_path, base_std),
        "size_match": (
            (gen_std.get("canvas") or {}).get("width"),
            (gen_std.get("canvas") or {}).get("height")) == (
            (base_std.get("canvas") or {}).get("width"),
            (base_std.get("canvas") or {}).get("height")),
        "side_by_side": None,
        "created_at": _now(),
    }
    if out_dir is not None:
        from PIL import Image

        with Image.open(generated_path) as g, \
                Image.open(baseline_path) as b:
            g = g.convert("RGBA")
            b = b.convert("RGBA")
        canvas = Image.new(
            "RGBA", (g.width + b.width, max(g.height, b.height)),
            (0, 0, 0, 0))
        canvas.paste(g, (0, 0))
        canvas.paste(b, (g.width, 0))
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        name = (f"compare_{generated_path.stem}_vs_{baseline_path.stem}"
                f".png")
        dest = out / name
        canvas.save(dest, format="PNG")
        data = dest.read_bytes()
        record["side_by_side"] = {
            "filename": name,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "width": canvas.width,
            "height": canvas.height,
        }
    return record
