#!/usr/bin/env python3
"""Zealandia skill FX pack runner (Plushy AI).

Generates all 39 assets from prompts/skill_fx/ to the exact placeholder
contract (filename, canvas, frame count) from skill_fx_manifest.tsv, so the
finals swap 1:1 into zealandia-skill-fx/placeholders/.

Rules (Plushy room runbook, 2026-10-21):
- Effects (type fx): transparent background (sprites.py default path).
- Icons (type icon): --no-bg-remove; the dark slate background is the design.
- Frame sheets: generated frame by frame at 512x512 (same prompt, the sheet
  clause replaced by a per-frame stage), then assembled into the exact strip.
- Singles are generated at 512 and downscaled to the contract size.

Usage (inside the plushy-ai Docker container, repo mounted at /app):
  python run_skill_fx.py [--only NAME] [--out DIR] [--seed N]
Outputs land in skill_fx_out/ by default.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROMPTS = ROOT / "prompts" / "skill_fx"
MANIFEST = ROOT / "skill_fx_manifest.tsv"
GEN_SIZE = 512

STAGES = [
    "just beginning, small and faint",
    "growing larger and brighter",
    "nearly full size",
    "at peak size and brightness",
    "shrinking and fading",
    "nearly gone, faint remnants",
]
SHEET_CLAUSE = re.compile(
    r",?\s*horizontal sprite sheet with exactly \d+ sequential animation "
    r"frames in one row, equal spacing, the effect grows then fades across "
    r"the frames")


def stage_for(k: int, frames: int) -> str:
    if frames == 1:
        return ""
    idx = round(k * (len(STAGES) - 1) / (frames - 1))
    return STAGES[idx]


def load_manifest():
    rows = []
    for line in MANIFEST.read_text().splitlines()[1:]:
        if not line.strip():
            continue
        name, typ, frames, frame_px = line.split("\t")
        rows.append((name, typ, int(frames), int(frame_px)))
    return rows


def generate_one(prompt: str, tmpdir: Path, keep_bg: bool, seed: int) -> Path:
    if tmpdir.exists():
        shutil.rmtree(tmpdir)
    tmpdir.mkdir(parents=True)
    cmd = [sys.executable, str(ROOT / "sprites.py"),
           "--prompt", prompt, "--output", str(tmpdir),
           "--size", str(GEN_SIZE), "--seed", str(seed)]
    if keep_bg:
        cmd.append("--no-bg-remove")
    r = subprocess.run(cmd, capture_output=True, text=True)
    pngs = sorted(tmpdir.glob("p00_*.png"))
    if r.returncode != 0 or not pngs:
        tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
        raise RuntimeError("generation failed: " + " | ".join(tail))
    return pngs[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="generate just this asset name")
    ap.add_argument("--out", default=str(ROOT / "skill_fx_out"))
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    from PIL import Image

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    tmp_root = outdir / ".tmp"
    rows = load_manifest()
    if args.only:
        rows = [r for r in rows if r[0] == args.only]
        if not rows:
            print(f"no such asset: {args.only}")
            return 1

    ok = failed = 0
    for i, (name, typ, frames, frame_px) in enumerate(rows, 1):
        prompt = (PROMPTS / f"{name}.txt").read_text().strip()
        keep_bg = typ == "icon"
        canvas = (frame_px * frames, frame_px)
        try:
            if frames == 1:
                src = generate_one(prompt, tmp_root / name, keep_bg, args.seed)
                img = Image.open(src).convert("RGBA")
                if img.size != canvas:
                    img = img.resize(canvas, Image.LANCZOS)
                img.save(outdir / f"{name}.png")
            else:
                base = SHEET_CLAUSE.sub("", prompt).strip().rstrip(",")
                strip = Image.new("RGBA", canvas, (0, 0, 0, 0))
                for k in range(frames):
                    stage = stage_for(k, frames)
                    fp = f"{base}, single animation frame, {stage}"
                    src = generate_one(fp, tmp_root / f"{name}_f{k}",
                                       keep_bg, args.seed + k)
                    frame = Image.open(src).convert("RGBA")
                    if frame.size != (frame_px, frame_px):
                        frame = frame.resize((frame_px, frame_px), Image.LANCZOS)
                    strip.paste(frame, (k * frame_px, 0))
                strip.save(outdir / f"{name}.png")
            ok += 1
            print(f"[{i}/{len(rows)}] {name}: ok -> {canvas[0]}x{canvas[1]}")
        except Exception as e:  # noqa: BLE001 - batch must not stop
            failed += 1
            print(f"[{i}/{len(rows)}] {name}: FAILED {e}")
    shutil.rmtree(tmp_root, ignore_errors=True)
    print(f"\ndone: {ok} ok, {failed} failed -> {outdir}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
