#!/usr/bin/env python3
"""Plushy-AI 2.0 Aseprite Bridge / Export - CLI (Phase 5).

Packages generated PNG layers and per-direction PNGs into an export
directory: verbatim PNG copies, one sprite sheet (4x2 grid, canonical
direction order), an optional layered .aseprite (written by the
built-in minimal writer and verified by round-tripping it through
the Phase 1 analyzer), and a versioned export manifest.

Usage:
    # per-direction set (any subset; missing directions are reported)
    python tools/export_assets.py --out ./export \
        --direction S=south.png --direction SE=se.png ...

    # named layers, with a layered .aseprite
    python tools/export_assets.py --out ./export \
        --layer body=body.png --layer hair=hair.png \
        --aseprite character.aseprite

    # preserve a source Aseprite's Phase 1 standard record
    python tools/export_assets.py --out ./export \
        --layer top=top.png --source-standard src.asset_standard.json

Originals are read-only. Exit code is 1 when the export manifest
status is needs_review (anything missing or flagged), so scripts can
gate on a clean export.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from exporter import DIRECTIONS, ExportError, export_assets  # noqa: E402


def _parse_pairs(items, flag):
    pairs = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"{flag} expects NAME=PATH, got {item!r}")
        key, path = item.split("=", 1)
        pairs[key.strip()] = path.strip()
    return pairs


def _parse_layers(items):
    layers = []
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"--layer expects NAME=PATH, got {item!r}")
        name, path = item.split("=", 1)
        layers.append((name.strip(), path.strip()))
    return layers


def main() -> int:
    ap = argparse.ArgumentParser(
        description="export PNG layers/directions with validation, "
                    "a sprite sheet and an optional layered .aseprite")
    ap.add_argument("--out", required=True, help="export output directory")
    ap.add_argument("--direction", action="append", default=[],
                    metavar="DIR=PATH",
                    help="per-direction PNG, DIR one of "
                         + ", ".join(DIRECTIONS) + " (repeatable)")
    ap.add_argument("--layer", action="append", default=[],
                    metavar="NAME=PATH",
                    help="named layer PNG (repeatable, order preserved)")
    ap.add_argument("--aseprite", default="",
                    help="also write a layered .aseprite with this "
                         "filename (requires --layer)")
    ap.add_argument("--sheet-name", default="sprite_sheet.png",
                    help="sprite sheet filename (default sprite_sheet.png)")
    ap.add_argument("--source-standard", default="",
                    help="Phase 1 asset-standard JSON to embed in the "
                         "export manifest (source metadata preservation)")
    ap.add_argument("--asset-id", default="export",
                    help="asset id recorded in the manifest")
    args = ap.parse_args()

    try:
        manifest = export_assets(
            args.out,
            direction_images=_parse_pairs(args.direction, "--direction"),
            layers=_parse_layers(args.layer),
            source_standard=args.source_standard or None,
            aseprite_name=args.aseprite or None,
            sheet_name=args.sheet_name,
            asset_id=args.asset_id)
    except ExportError as e:
        print(f"ERROR: {e}")
        return 1

    print(f"export status={manifest['status']} -> "
          f"{Path(args.out) / 'export_manifest.json'}")
    for entry in manifest["directions"]:
        line = f"  direction {entry['direction']}: {entry['status']}"
        if entry["status"] != "missing":
            line += (f" {entry['width']}x{entry['height']} "
                     f"alpha={entry['has_alpha']} "
                     f"packed={entry['packed']}")
        print(line)
        for w in entry["warnings"]:
            print(f"    warning: {w}")
    for entry in manifest["layers"]:
        print(f"  layer {entry['name']}: {entry['status']} "
              f"{entry['width']}x{entry['height']} "
              f"alpha={entry['has_alpha']}")
        for w in entry["warnings"]:
            print(f"    warning: {w}")
    outputs = manifest["outputs"]
    if outputs["sprite_sheet"]:
        sheet = outputs["sprite_sheet"]
        print(f"  sprite sheet: {sheet['filename']} "
              f"{sheet['width']}x{sheet['height']} "
              f"({sheet['layout']['columns']}x{sheet['layout']['rows']} grid)")
    if outputs["aseprite"]:
        ase = outputs["aseprite"]
        print(f"  aseprite: {ase['filename']} status={ase['status']}")
        if ase["reason"]:
            print(f"    reason: {ase['reason']}")
        if ase["roundtrip"]:
            print(f"    round-trip ({ase['roundtrip']['checker']}): "
                  f"{ase['roundtrip']['status']}, "
                  f"layers={ase['roundtrip']['layers']}")
    if manifest["source_standard"]:
        print(f"  source standard preserved: "
              f"{manifest['source_standard']['filename']} "
              f"sha256={manifest['source_standard']['sha256'][:16]}...")
    return 0 if manifest["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
