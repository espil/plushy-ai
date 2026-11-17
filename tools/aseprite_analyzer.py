#!/usr/bin/env python3
"""Plushy-AI 2.0 Asset Standard Engine - CLI (Phase 1).

Analyzes PNG / Aseprite files and writes one versioned asset-standard
JSON per input: <asset_id>.asset_standard.json.

Usage:
    python tools/aseprite_analyzer.py path/to/asset.aseprite [more files]
    python tools/aseprite_analyzer.py asset.png --out ./standards

Originals are opened read-only and never modified. Exit code is 1 when
any input fails analysis (the error is printed, other files still run).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from asset_standard import AssetAnalysisError, analyze_file  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="analyze assets into the "
                                             "Espil asset-standard JSON")
    ap.add_argument("files", nargs="+", help="PNG or .ase/.aseprite files")
    ap.add_argument("--out", default="",
                    help="output directory (default: alongside each input)")
    args = ap.parse_args()

    failures = 0
    for name in args.files:
        path = Path(name)
        try:
            std = analyze_file(path)
        except AssetAnalysisError as e:
            print(f"ERROR {path}: {e}")
            failures += 1
            continue
        out_dir = Path(args.out) if args.out else path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{std['asset_id']}.asset_standard.json"
        dest.write_text(json.dumps(std, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        canvas = std["canvas"]
        print(f"{path.name}: {canvas['width']}x{canvas['height']} "
              f"{canvas['color_mode']}, {len(std['frames'])} frame(s), "
              f"{len(std['layers'])} layer(s), "
              f"status={std['validation']['status']} -> {dest}")
        for w in std["validation"]["warnings"]:
            print(f"  warning: {w}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
