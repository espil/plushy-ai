#!/usr/bin/env python3
"""Plushy-AI 2.0 Asset Generator - CLI (Phase 3).

Generates sprite assets through the existing 1.0 pipeline
(pipeline_sprite), recording every job as a versioned JSON record.

Usage:
    PLUSHY_MOCK=1 python tools/asset_generator.py "a red hoodie" \
        --category Top --seed 42 --variations 2 --size 256
    PLUSHY_MOCK=1 python tools/asset_generator.py "blue version" \
        --reference ref.png --category Top
    ... --reference ref.png --mask-record mask.json --claim-region

The backend is printed plainly: with PLUSHY_MOCK=1 the outputs are
procedural MOCK placeholders, not model generations. Region-targeted
generation (--claim-region) is refused without a confirmed, non-empty
mask record from Phase 2. Inpainting is unsupported (see
docs/STYLE_AND_GENERATION.md). Exit code is 1 on any failure.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generator import (  # noqa: E402
    GeneratorError,
    backend_name,
    inpainting_status,
    list_profiles,
    run_generation,
)
from reference import analyze_reference  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description="generate sprite assets (Phase 3)")
    ap.add_argument("prompt", nargs="?", default="",
                    help="user prompt (preserved verbatim in the record)")
    ap.add_argument("--category", default="",
                    help="Phase 2 category (Hair, Face, Top, ...)")
    ap.add_argument("--profile", default="sprite-default",
                    help="style profile id (see --list-profiles)")
    ap.add_argument("--list-profiles", action="store_true",
                    help="list style profiles and exit")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--variations", type=int, default=1)
    ap.add_argument("--size", type=int, default=0,
                    help="square output size (default: profile size)")
    ap.add_argument("--steps", type=int, default=6)
    ap.add_argument("--negative-prompt", default="")
    ap.add_argument("--reference", default="",
                    help="reference image path for img2img generation")
    ap.add_argument("--strength", type=float, default=0.6)
    ap.add_argument("--mask-record", default="",
                    help="Phase 2 mask metadata JSON (for --claim-region)")
    ap.add_argument("--claim-region", action="store_true",
                    help="claim a mask target region (requires a "
                         "confirmed mask record)")
    ap.add_argument("--inpaint", action="store_true",
                    help="request inpainting (unsupported; will refuse)")
    ap.add_argument("--out", default="",
                    help="output directory (default: ./generated)")
    args = ap.parse_args()

    if args.list_profiles:
        for p in list_profiles():
            state = "enabled" if p["enabled"] \
                else f"DISABLED: {p['disabled_reason']}"
            print(f"{p['profile_id']}: rendering_mode="
                  f"{p['rendering_mode']} pipeline_style="
                  f"{p['pipeline_style']} - {state}")
        st = inpainting_status()
        print(f"inpainting: {st['status']} - {st['reason']}")
        return 0

    if not args.prompt:
        print("ERROR: a prompt is required")
        return 1

    backend = backend_name()
    print(f"backend: {backend}"
          + (" (MOCK - procedural placeholders, NOT model output)"
             if backend == "mock" else " (SDXL-Turbo)"))

    reference_record = None
    if args.reference:
        try:
            reference_record = analyze_reference(
                args.reference, category=args.category or None)
        except Exception as e:  # noqa: BLE001
            print(f"ERROR reference: {e}")
            return 1

    mask_record = None
    if args.mask_record:
        try:
            mask_record = json.loads(
                Path(args.mask_record).read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"ERROR mask record: {e}")
            return 1

    out_dir = Path(args.out) if args.out else Path("generated")
    try:
        record = run_generation(
            args.prompt, out_dir,
            category=args.category or None,
            profile_id=args.profile,
            seed=args.seed,
            variations=args.variations,
            width=args.size or None,
            height=args.size or None,
            steps=args.steps,
            negative_prompt=args.negative_prompt or None,
            reference_record=reference_record,
            reference_image_path=args.reference or None,
            strength=args.strength,
            claim_region=args.claim_region,
            mask_record=mask_record,
            inpaint=args.inpaint,
        )
    except GeneratorError as e:
        print(f"ERROR: {e}")
        return 1

    print(f"job {record['job_id']}: status={record['status']} "
          f"mode={record['mode']} backend={record['backend']} "
          f"category={record['category']} "
          f"profile={record['style_profile_id']} "
          f"seeds={record['seeds']} region={record['region']}")
    for o in record["outputs"]:
        print(f"  output: {o['filename']} seed={o['seed']} "
              f"sha256={o['sha256'][:12]}...")
    print(f"  job record: {out_dir / record['job_filename']}")
    if record["backend"] == "mock":
        print("  NOTE: MOCK backend - outputs are placeholders.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
