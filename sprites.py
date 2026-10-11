#!/usr/bin/env python3
"""
sprites.py — batch text-to-sprite generation.

One prompt per line in a text file (# = comment, blank lines skipped),
or a single --prompt. Outputs transparent PNGs + manifest.json.

Usage:
  python sprites.py --prompt "a pine tree" --output ./my_sprites
  python sprites.py --prompts prompts.txt --output ./my_sprites --seeds 3
  python sprites.py --prompts prompts.txt --output ./my_sprites --size 256 --skip-existing

Environment:
  PLUSHY_MOCK=1   placeholder sprites, no GPU/model needed
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path


def slugify(prompt: str, max_words: int = 5) -> str:
    words = re.sub(r"[^a-z0-9 ]", "", prompt.lower()).split()[:max_words]
    return "_".join(words) or "sprite"


def load_prompts(path: Path):
    prompts = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            prompts.append(line)
    return prompts


def main():
    ap = argparse.ArgumentParser(description="Batch text-to-transparent-PNG sprites.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--prompt", help="single prompt")
    src.add_argument("--prompts", help="text file, one prompt per line")
    ap.add_argument("--output", required=True, help="output directory")
    ap.add_argument("--size", type=int, default=512, help="square size px")
    ap.add_argument("--width", type=int, default=None)
    ap.add_argument("--height", type=int, default=None)
    ap.add_argument("--seed", type=int, default=0, help="base seed")
    ap.add_argument("--seeds", type=int, default=1, help="seeds per prompt (0..N-1 from --seed)")
    ap.add_argument("--steps", type=int, default=4, help="inference steps (SDXL-Turbo: 1-4)")
    ap.add_argument("--no-bg-remove", action="store_true", help="skip background removal")
    ap.add_argument("--negative", default=None,
                    help="negative prompt (overrides default)")
    ap.add_argument("--mock", action="store_true", help="force mock mode")
    ap.add_argument("--skip-existing", action="store_true")
    args = ap.parse_args()

    if args.mock:
        os.environ["PLUSHY_MOCK"] = "1"

    from pipeline_sprite import SpritePipeline, SpriteOptions

    prompts = [args.prompt] if args.prompt else load_prompts(Path(args.prompts))
    if not prompts:
        sys.exit("no prompts found")
    outdir = Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)

    width = args.width or args.size
    height = args.height or args.size

    pipe = SpritePipeline()
    manifest = []
    ok = failed = 0
    t0 = time.time()
    total = len(prompts) * args.seeds
    done = 0
    print(f"sprites: {len(prompts)} prompt(s) x {args.seeds} seed(s) -> {outdir}")
    for prompt in prompts:
        for s in range(args.seeds):
            seed = args.seed + s
            slug = slugify(prompt)
            name = f"{slug}_s{seed}.png" if args.seeds > 1 else f"{slug}.png"
            dest = outdir / name
            entry = {"prompt": prompt, "seed": seed, "file": name}
            if args.skip_existing and dest.exists():
                entry["status"] = "skipped"
                manifest.append(entry)
                done += 1
                continue
            try:
                opts = SpriteOptions(
                    width=width, height=height, seed=seed,
                    num_inference_steps=args.steps,
                    remove_background=not args.no_bg_remove,
                )
                if args.negative:
                    opts.negative_prompt = args.negative
                pipe.generate_to_file(prompt, dest, opts)
                entry["status"] = "ok"
                ok += 1
            except Exception as e:  # noqa: BLE001 - batch must not stop
                entry["status"] = "failed"
                entry["error"] = f"{type(e).__name__}: {e}"
                failed += 1
            manifest.append(entry)
            done += 1
            print(f"  [{done}/{total}] {name}: {entry['status']}")
    dt = time.time() - t0
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"\ndone: {ok} ok, {failed} failed, {dt:.0f}s total")
    print(f"manifest -> {outdir}/manifest.json")


if __name__ == "__main__":
    main()
