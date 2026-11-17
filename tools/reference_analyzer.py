#!/usr/bin/env python3
"""Plushy-AI 2.0 Reference Analyzer - CLI (Phase 2).

Ingests reference images (PNG/JPG/WEBP) the way an upload would be
handled: full content validation, storage under a generated safe ID,
Phase 1 asset-standard analysis, and a reference record JSON linking
the analysis back to the original image.

Usage:
    python tools/reference_analyzer.py ref.png [--category Hair]
    python tools/reference_analyzer.py ref.png --out ./refs
    python tools/reference_analyzer.py ref.png --suggest-mask

--suggest-mask also writes an UNCONFIRMED suggested mask (transparent
PNG + metadata JSON). A suggestion is never a generation target; only
a user-confirmed mask record has one. Originals are opened read-only
and never modified. Exit code is 1 when any input fails.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reference import (  # noqa: E402
    CATEGORIES,
    ReferenceError,
    ingest_reference,
    save_mask,
    suggest_mask,
)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="ingest and analyze reference images (Phase 2)")
    ap.add_argument("files", nargs="+", help="PNG/JPG/WEBP reference images")
    ap.add_argument("--out", default="",
                    help="storage directory (default: ./references)")
    ap.add_argument("--category", default="", choices=["", *CATEGORIES],
                    help="asset category for the reference(s)")
    ap.add_argument("--suggest-mask", action="store_true",
                    help="also write an unconfirmed suggested mask")
    args = ap.parse_args()

    out_dir = Path(args.out) if args.out else Path("references")
    failures = 0
    for name in args.files:
        path = Path(name)
        try:
            record = ingest_reference(
                path.read_bytes(), path.name, out_dir,
                category=args.category or None)
        except (ReferenceError, OSError) as e:
            print(f"ERROR {path}: {e}")
            failures += 1
            continue
        src = record["source"]
        canvas = record["asset_standard"]["canvas"]
        print(f"{path.name}: -> {src['stored_filename']} "
              f"({src['format']}, {canvas['width']}x{canvas['height']}, "
              f"sha256={src['sha256'][:12]}..., "
              f"category={record['category']})")
        if args.suggest_mask:
            mask = suggest_mask(record)
            mask_path = out_dir / f"{record['reference_id']}.suggested_mask.png"
            mrec = save_mask(mask, mask_path, record, confirmed=False)
            print(f"  suggested mask (UNCONFIRMED, not a generation "
                  f"target): {mask_path} bounds={mrec['bounds']}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
