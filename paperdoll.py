#!/usr/bin/env python3
"""Paper-doll character pipeline: 8-direction sprites on a blank body.

Workflow:
  1. Generate blank bodies (8 dirs, M/F):
       python sprites.py --prompts prompts/char_body_male.txt --style 2.5d \\
           --seeds 1 --size 512 --output ./paperdoll/bodies/male
  2. Wear items on each body direction (img2img), extract transparent layers:
       python paperdoll.py batch --body-dir ./paperdoll/bodies/male \\
           --prompts prompts/char_items_tops.txt --strength 0.6 \\
           --out ./paperdoll/layers/tops
  3. Compose a character from layers:
       python paperdoll.py compose --body ./paperdoll/bodies/male/body_S_s0.png \\
           --layers ./paperdoll/layers/hair/bob_S.png,./paperdoll/layers/tops/hoodie_S.png \\
           --out ./paperdoll/chars/char01_S.png

Layer order for compose: hair_back, body, bottoms, tops, shoes, face, hair_front.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_sprite import SpritePipeline, SpriteOptions  # noqa: E402


def load_prompts(path: Path):
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def extract_layer(worn, body, thresh: int = 28):
    """Transparent layer = pixels the img2img pass changed vs the blank body.

    worn/body are RGBA PIL images of the same size. Returns RGBA where only
    changed pixels are opaque (crisp alpha).
    """
    import numpy as np
    from PIL import Image
    w = np.array(worn.convert("RGBA")).astype(int)
    b = np.array(body.convert("RGBA")).astype(int)
    # only compare where at least one side is opaque
    opaque = (w[:, :, 3] > 127) | (b[:, :, 3] > 127)
    diff = np.abs(w[:, :, :3] - b[:, :, :3]).max(axis=2)
    mask = opaque & (diff > thresh)
    # cleanup: drop isolated specks (3x3 majority)
    from PIL import Image as I
    m = I.fromarray((mask * 255).astype(np.uint8))
    m = m.filter(__import__("PIL.ImageFilter", fromlist=["MedianFilter"]).MedianFilter(3))
    mask = np.array(m) > 127
    layer = np.zeros_like(w, dtype=np.uint8)
    layer[mask] = np.clip(w[mask], 0, 255).astype(np.uint8)
    layer[:, :, 3] = np.where(mask, 255, 0).astype(np.uint8)
    return Image.fromarray(layer)


def cmd_wear(args):
    from PIL import Image
    pipe = SpritePipeline()
    body = Image.open(args.body).convert("RGBA")
    opts = SpriteOptions(seed=args.seed, num_inference_steps=args.steps,
                         style=args.style)
    worn = pipe.img2img(args.prompt, body, strength=args.strength, opts=opts)
    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    worn.save(dest)
    print(f"worn -> {dest}")


def cmd_batch(args):
    from PIL import Image
    pipe = SpritePipeline()
    prompts = load_prompts(Path(args.prompts))
    body_dir = Path(args.body_dir)
    bodies = sorted(body_dir.glob("*.png"))
    if not bodies:
        print(f"no body PNGs in {body_dir}", file=sys.stderr)
        sys.exit(1)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for body_path in bodies:
        # direction tag = middle part of "<name>_<DIR>_s<N>.png", e.g. body_S_s0
        stem = body_path.stem
        direction = stem.split("_")[-2] if "_" in stem else "S"
        body = Image.open(body_path).convert("RGBA")
        for pi, prompt in enumerate(prompts):
            for s in range(args.seeds):
                seed = args.seed + s
                opts = SpriteOptions(seed=seed,
                                     num_inference_steps=args.steps,
                                     style=args.style)
                worn = pipe.img2img(prompt, body, strength=args.strength,
                                    opts=opts)
                tag = f"{direction}_p{pi}_s{seed}"
                worn_path = out_dir / f"worn_{tag}.png"
                worn.save(worn_path)
                layer = extract_layer(worn, body, thresh=args.diff_thresh)
                layer_path = out_dir / f"layer_{tag}.png"
                layer.save(layer_path)
                manifest.append({"prompt": prompt, "body": body_path.name,
                                 "direction": direction, "seed": seed,
                                 "worn": worn_path.name,
                                 "layer": layer_path.name})
                print(f"  {layer_path.name}")
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"done: {len(manifest)} layers -> {out_dir}")


def cmd_compose(args):
    from PIL import Image
    body = Image.open(args.body).convert("RGBA")
    canvas = body.copy()
    for lp in args.layers.split(","):
        lp = lp.strip()
        if not lp:
            continue
        layer = Image.open(lp).convert("RGBA")
        if layer.size != canvas.size:
            layer = layer.resize(canvas.size)
        canvas = Image.alpha_composite(canvas, layer)
    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest)
    print(f"composed -> {dest} ({1 + len(args.layers.split(','))} layers)")


def main():
    ap = argparse.ArgumentParser(description="paper-doll character pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("wear", help="img2img one item onto one body image")
    w.add_argument("--body", required=True)
    w.add_argument("--prompt", required=True)
    w.add_argument("--strength", type=float, default=0.6)
    w.add_argument("--seed", type=int, default=0)
    w.add_argument("--steps", type=int, default=6)
    w.add_argument("--style", default="2.5d", choices=["default", "2.5d", "3d"])
    w.add_argument("--out", required=True)
    w.set_defaults(fn=cmd_wear)

    b = sub.add_parser("batch", help="wear every prompt on every body direction")
    b.add_argument("--body-dir", required=True)
    b.add_argument("--prompts", required=True)
    b.add_argument("--strength", type=float, default=0.6)
    b.add_argument("--seed", type=int, default=0)
    b.add_argument("--seeds", type=int, default=1)
    b.add_argument("--steps", type=int, default=6)
    b.add_argument("--style", default="2.5d", choices=["default", "2.5d", "3d"])
    b.add_argument("--diff-thresh", type=int, default=28,
                   help="pixel-diff threshold for layer extraction")
    b.add_argument("--out", required=True)
    b.set_defaults(fn=cmd_batch)

    c = sub.add_parser("compose", help="composite body + layers")
    c.add_argument("--body", required=True)
    c.add_argument("--layers", required=True,
                   help="comma-separated layer PNGs, back-to-front order")
    c.add_argument("--out", required=True)
    c.set_defaults(fn=cmd_compose)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
