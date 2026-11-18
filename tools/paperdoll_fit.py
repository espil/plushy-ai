#!/usr/bin/env python3
"""Plushy-AI 2.0 Paper Doll Fit - CLI (Phase 4).

Fits item layers onto blank bodies with VALIDATION (no silent
resize, unlike 1.0 `paperdoll.py compose`) and writes a versioned
manifest accounting for all 8 directions.

Usage:
    python tools/paperdoll_fit.py \
        --body-dir ./paperdoll/bodies/female \
        --layer tops=./layers/hoodie.png \
        --layer hair_front=./layers/hair_dir \
        --out ./paperdoll/fit/char01
    python tools/paperdoll_fit.py --body body_S_s0.png --direction S \
        --layer tops=hoodie_S.png --out ./out
    ... --generation-record gen.job.json --generation-slot tops

Each --layer is SLOT=PATH where PATH is one PNG (used for the
direction its filename names, or every direction if it names none)
or a directory of per-direction PNGs. Slots: hair_back, bottoms,
tops, shoes, face, hair_front. A Phase 3 generation record is
linked only when the layer file's sha256 matches a recorded
generation output. Exit code is 1 on any failure; directions that
are missing or need review are reported, not hidden.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fitting import (  # noqa: E402
    COMPOSE_ORDER,
    DIRECTIONS,
    FittingError,
    discover_bodies,
    fit_layers,
)


def _parse_layers(items):
    layers = []
    for item in items or []:
        if "=" not in item:
            raise FittingError(
                f"--layer must be SLOT=PATH, got {item!r}")
        slot, raw = item.split("=", 1)
        path = Path(raw)
        if path.is_dir():
            layers.append({"slot": slot.strip(), "dir": str(path)})
        else:
            layers.append({"slot": slot.strip(), "path": str(path)})
    return layers


def main() -> int:
    ap = argparse.ArgumentParser(
        description="fit paper-doll layers with validation (Phase 4)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--body-dir", default="",
                     help="directory of per-direction body PNGs")
    src.add_argument("--body", default="",
                     help="a single body PNG (see --direction)")
    ap.add_argument("--direction", default="S",
                    choices=list(DIRECTIONS),
                    help="direction of --body (default S)")
    ap.add_argument("--body-pattern", default="*.png",
                    help="glob filter for bodies in --body-dir "
                         "(e.g. '*_s0.png', as in paperdoll batch)")
    ap.add_argument("--directions", default="",
                    help="comma-separated direction list mapping "
                         "p{NN}_ body files by prompt index "
                         "(paperdoll batch convention)")
    ap.add_argument("--layer", action="append", default=[],
                    help="SLOT=PATH_OR_DIR, repeatable; slots: "
                         + ", ".join(s for s in COMPOSE_ORDER
                                     if s != "body"))
    ap.add_argument("--generation-record", default="",
                    help="Phase 3 job record JSON to link")
    ap.add_argument("--generation-slot", default="",
                    help="slot the generated output is used as")
    ap.add_argument("--generation-output", default="",
                    help="specific output filename in the record")
    ap.add_argument("--out", required=True, help="output directory")
    args = ap.parse_args()

    try:
        layers = _parse_layers(args.layer)
        if not layers:
            raise FittingError("at least one --layer is required")
        if args.body_dir:
            directions = ([d.strip() for d in
                           args.directions.split(",") if d.strip()]
                          or None)
            bodies, _dup = discover_bodies(
                args.body_dir, pattern=args.body_pattern,
                directions=directions)
        else:
            bodies = {args.direction: Path(args.body)}
        generation = None
        if args.generation_record:
            if not args.generation_slot:
                raise FittingError(
                    "--generation-record needs --generation-slot")
            generation = {
                "record": args.generation_record,
                "slot": args.generation_slot,
                "output": args.generation_output or None,
            }
        manifest = fit_layers(bodies, layers, args.out,
                              generation=generation)
    except FittingError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    for entry in manifest["entries"]:
        line = f"{entry['direction']}: {entry['status']}"
        if entry["missing"]:
            line += f" (missing: {', '.join(entry['missing'])})"
        if entry["status"] == "needs_review":
            line += " (size mismatch - not composed)"
        print(line)
    gen = manifest["generation"]
    print("generation: " + (
        f"{gen['job_id']} slot={gen['slot']} "
        f"output={gen['output_filename']}" if gen else "none"))
    print(f"anchors: None (no anchor data in baseline assets)")
    s = manifest["summary"]
    print(f"summary: ok={s['ok']} missing={s['missing']} "
          f"needs_review={s['needs_review']}")
    print(f"manifest -> {Path(args.out) / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
