"""Paper Doll Integration for Plushy-AI 2.0 (Phase 4).

Fits item layers onto blank-body sprites and records the result in a
versioned manifest. This module is a 2.0-side companion to the 1.0
`paperdoll.py`: it REUSES paperdoll by importing it
(`paperdoll.load_prompts`, `paperdoll.extract_layer`, and paperdoll's
documented compose layer order) and never modifies it.

Headline difference from 1.0 `paperdoll.py compose`: 1.0 silently
resizes any layer whose size differs from the body canvas. This
module VALIDATES instead - a size mismatch marks the direction
"needs_review" in the manifest, records both sizes, and produces no
composite. Nothing is ever resized to fit.

Composition model (the existing paperdoll model, stated plainly):
layers share the body canvas and are alpha-composited at the same
origin in the canonical order

    hair_back, body, bottoms, tops, shoes, face, hair_front

There are no fitting coordinates or anchors in the baseline assets,
so anchors stay None everywhere - no coordinate is guessed.

Inputs are read-only: body and layer files are never overwritten;
all outputs go to a separate output directory under generated safe
names. All 8 directions (S, SE, E, NE, N, NW, W, SW) are always
accounted for in the manifest: a direction whose body or layer file
is absent is marked "missing" (naming the missing side) instead of
being silently skipped.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_SCHEMA_VERSION = "1.0"

DIRECTIONS = ("S", "SE", "E", "NE", "N", "NW", "W", "SW")

# Canonical compose order, from paperdoll.py's module docstring:
# "Layer order for compose: hair_back, body, bottoms, tops, shoes,
# face, hair_front."
COMPOSE_ORDER = ("hair_back", "body", "bottoms", "tops", "shoes",
                 "face", "hair_front")

# Slots a caller may supply as item layers ("body" is the base, never
# a supplied layer).
LAYER_SLOTS = tuple(s for s in COMPOSE_ORDER if s != "body")

ANCHORS_NOTE = (
    "anchors are None: no anchor or fitting-coordinate data exists "
    "in the baseline body/item assets, and none is guessed. "
    "Composition is same-canvas overlay only (the paperdoll model: "
    "layers share the body canvas)."
)

COMPOSITION_MODEL = "same_canvas_overlay"


class FittingError(Exception):
    """Raised for invalid fit requests and generation-linkage errors."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _paperdoll():
    """Import 1.0 paperdoll lazily (it imports pipeline_sprite)."""
    import paperdoll

    return paperdoll


def load_prompts(path):
    """Delegate to paperdoll.load_prompts (1.0 reuse, not a copy)."""
    return _paperdoll().load_prompts(Path(path))


def extract_layer(worn_path, body_path, thresh: int = 28,
                  out_path=None):
    """Extract a transparent item layer via paperdoll.extract_layer.

    worn/body are image paths of the same size; `thresh` is
    paperdoll's pixel-diff threshold (default 28, as in 1.0). Returns
    the RGBA layer image; if out_path is given, also saves it there.
    The input files are only read.
    """
    from PIL import Image

    paperdoll = _paperdoll()
    with Image.open(worn_path) as w, Image.open(body_path) as b:
        layer = paperdoll.extract_layer(w.convert("RGBA"),
                                        b.convert("RGBA"),
                                        thresh=thresh)
    if out_path is not None:
        dest = Path(out_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        layer.save(dest)
    return layer


# ---------------------------------------------------------------------------
# Discovery (following paperdoll's own naming conventions)
# ---------------------------------------------------------------------------

def direction_from_filename(name: str, directions=None) -> str | None:
    """Direction encoded in a filename, or None.

    Follows paperdoll.batch's conventions: a ``p{NN}_`` prefix maps
    through the caller-supplied directions list by prompt index;
    otherwise a ``_<DIR>_`` / trailing ``_<DIR>`` token in the stem
    (e.g. body_S_s0.png, layer_SE_p0_s0.png) names the direction.
    """
    stem = Path(name).stem
    m = re.match(r"p(\d+)_", stem)
    if m and directions:
        return directions[int(m.group(1)) % len(directions)].strip()
    tokens = stem.split("_")
    for token in tokens:
        if token in DIRECTIONS:
            return token
    return None


def _discover(directory, pattern="*.png", directions=None):
    """Map direction -> first sorted file in `directory` for it."""
    found: dict[str, Path] = {}
    duplicates: dict[str, list[str]] = {}
    for path in sorted(Path(directory).glob(pattern)):
        if not path.is_file():
            continue
        direction = direction_from_filename(path.name, directions)
        if direction is None:
            continue
        if direction in found:
            duplicates.setdefault(direction, []).append(path.name)
        else:
            found[direction] = path
    return found, duplicates


def discover_bodies(body_dir, pattern="*.png", directions=None):
    """Direction -> body file, following paperdoll body naming."""
    return _discover(body_dir, pattern, directions)


def discover_layers(layer_dir, pattern="*.png", directions=None):
    """Direction -> layer file inside a per-direction layer folder."""
    return _discover(layer_dir, pattern, directions)


# ---------------------------------------------------------------------------
# Generation-record linkage (Phase 3)
# ---------------------------------------------------------------------------

def _load_generation(generation, layers_by_direction):
    """Validate and normalize the optional Phase 3 generation link.

    `generation` is None or a dict with keys:
      record: job record dict or path to a `<job_id>.job.json`
      slot:   the layer slot the generated output is used as
      output: optional output filename inside the record

    Returns the manifest "generation" block. Raises FittingError if
    the record does not contain an output whose sha256 matches the
    layer file actually used for that slot in some direction - the
    link must be proven by content hash, not by filename alone.
    """
    if generation is None:
        return None
    record = generation.get("record")
    if isinstance(record, (str, Path)):
        record = json.loads(Path(record).read_text(encoding="utf-8"))
    if not isinstance(record, dict) or "job_id" not in record:
        raise FittingError("generation record has no job_id")
    slot = generation.get("slot")
    if slot not in LAYER_SLOTS:
        raise FittingError(
            f"generation slot must be one of {LAYER_SLOTS}, got {slot!r}")
    outputs = record.get("outputs") or []
    wanted = generation.get("output")
    candidates = [o for o in outputs
                  if wanted is None or o.get("filename") == wanted]
    if not candidates:
        raise FittingError(
            f"generation output {wanted!r} not in job record "
            f"{record['job_id']}")
    candidate_shas = {o.get("sha256") for o in candidates}
    used_sha = None
    for direction in DIRECTIONS:
        layer_path = layers_by_direction.get(direction, {}).get(slot)
        if layer_path is not None:
            sha = _sha256_file(layer_path)
            if sha in candidate_shas:
                used_sha = sha
                break
    if used_sha is None:
        raise FittingError(
            "no layer file for slot "
            f"{slot!r} matches a generation output sha256 in job "
            f"{record['job_id']}; refusing to claim the link")
    matched = next(o for o in candidates if o.get("sha256") == used_sha)
    return {
        "job_id": record["job_id"],
        "slot": slot,
        "output_filename": matched.get("filename"),
        "output_sha256": used_sha,
        "backend": record.get("backend"),
    }


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------

def _layer_spec(layers):
    """Normalize the caller's layer list.

    Each layer is a dict: {slot, path} for one file used for every
    direction it names (or all directions if its filename carries no
    direction), or {slot, dir} for a folder of per-direction files.
    Returns (spec, per-direction map direction -> {slot: Path}).
    """
    spec = []
    per_direction: dict[str, dict[str, Path]] = {d: {} for d in DIRECTIONS}
    for layer in layers or []:
        slot = layer.get("slot")
        if slot not in LAYER_SLOTS:
            raise FittingError(
                f"layer slot must be one of {LAYER_SLOTS}, got {slot!r}")
        name = layer.get("name")
        if "dir" in layer:
            found, _dup = discover_layers(layer["dir"])
            spec.append({"slot": slot, "name": name,
                         "source_dir": str(layer["dir"]),
                         "files": {d: p.name for d, p in found.items()}})
            for direction, path in found.items():
                per_direction[direction].setdefault(slot, path)
        elif "path" in layer:
            path = Path(layer["path"])
            if not path.is_file():
                raise FittingError(f"layer file not found: {path}")
            named = direction_from_filename(path.name)
            spec.append({"slot": slot, "name": name or path.stem,
                         "source_file": path.name})
            targets = (named,) if named else DIRECTIONS
            for direction in targets:
                per_direction[direction].setdefault(slot, path)
        else:
            raise FittingError("each layer needs 'path' or 'dir'")
    return spec, per_direction


def fit_layers(bodies, layers, out_dir, generation=None,
               fit_id=None) -> dict:
    """Fit layers onto bodies and write the manifest + previews.

    bodies: direction -> body PNG path (missing directions are
        simply absent keys; use discover_bodies or a single-entry
        dict for --body mode).
    layers: layer spec list as in _layer_spec.
    generation: optional Phase 3 linkage dict (see _load_generation)
        or None, recorded as generation: None.

    Returns the manifest dict; also written to
    `<out_dir>/manifest.json`. Per direction, a valid fit writes the
    layer copies `layer_{DIR}_{slot}.png` and the composite
    `worn_{DIR}.png`. Mismatched directions write NO outputs.
    """
    from PIL import Image

    from asset_standard import analyze_file

    spec, per_direction = _layer_spec(layers)
    generation_block = _load_generation(generation, per_direction)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    supplied_slots = [s["slot"] for s in spec]
    ordered_slots = [s for s in COMPOSE_ORDER if s in supplied_slots]

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "fit_id": fit_id or ("fit_" + hashlib.sha256(
            _now().encode()).hexdigest()[:16]),
        "created_at": _now(),
        "composition_model": COMPOSITION_MODEL,
        "compose_order": list(COMPOSE_ORDER),
        "directions_order": list(DIRECTIONS),
        "anchors": None,
        "anchors_note": ANCHORS_NOTE,
        "generation": generation_block,
        "layers_spec": spec,
        "entries": [],
        "summary": {"ok": 0, "missing": 0, "needs_review": 0},
    }

    for direction in DIRECTIONS:
        entry = {
            "direction": direction,
            "status": None,
            "missing": [],
            "body": None,
            "layers": [],
            "validation": None,
            "anchors": None,
            "outputs": None,
            "notes": [],
        }
        body_path = bodies.get(direction)
        layer_paths = per_direction.get(direction, {})
        if body_path is None:
            entry["missing"].append("body")
        for slot in ordered_slots:
            if slot not in layer_paths:
                entry["missing"].append(f"layer:{slot}")
        if entry["missing"]:
            entry["status"] = "missing"
            manifest["summary"]["missing"] += 1
            manifest["entries"].append(entry)
            continue

        body_path = Path(body_path)
        entry["body"] = {"filename": body_path.name,
                         "sha256": _sha256_file(body_path)}
        with Image.open(body_path) as im:
            body_img = im.convert("RGBA").copy()
        body_size = body_img.size

        layer_imgs = {}
        size_ok = True
        for slot in ordered_slots:
            path = Path(layer_paths[slot])
            with Image.open(path) as im:
                layer_img = im.convert("RGBA").copy()
            layer_imgs[slot] = layer_img
            if layer_img.size != body_size:
                size_ok = False
            entry["layers"].append({
                "slot": slot,
                "name": next(
                    (s.get("name") for s in spec if s["slot"] == slot),
                    None) or path.stem,
                "filename": path.name,
                "sha256": _sha256_file(path),
                "size": {"width": layer_img.size[0],
                         "height": layer_img.size[1]},
                "compose_index": COMPOSE_ORDER.index(slot),
            })
        entry["layers"].sort(key=lambda e: e["compose_index"])

        # Alignment evidence: measured content bounds only (Phase 1).
        alignment = {
            "body_content_bounds": analyze_file(body_path).get(
                "content_bounds"),
            "layers": {},
        }
        for slot in ordered_slots:
            alignment["layers"][slot] = analyze_file(
                layer_paths[slot]).get("content_bounds")
        entry["validation"] = {
            "size_match": size_ok,
            "body_size": {"width": body_size[0],
                          "height": body_size[1]},
            "alignment": alignment,
            "alignment_note": (
                "content_bounds are measured by the Phase 1 "
                "analyzer and recorded side by side; no alignment "
                "beyond these measurements is claimed."),
            "status": "ok" if size_ok else "needs_review",
        }
        if not size_ok:
            entry["status"] = "needs_review"
            entry["notes"].append(
                "layer canvas size differs from the body canvas; "
                "NOT resized and NOT composed (1.0 compose would "
                "have silently resized it)")
            manifest["summary"]["needs_review"] += 1
            manifest["entries"].append(entry)
            continue

        # Compose in the canonical order: hair_back under the body,
        # then bottoms, tops, shoes, face, hair_front over it.
        canvas = Image.new("RGBA", body_size, (0, 0, 0, 0))
        if "hair_back" in layer_imgs:
            canvas = Image.alpha_composite(canvas,
                                           layer_imgs["hair_back"])
        canvas = Image.alpha_composite(canvas, body_img)
        for slot in COMPOSE_ORDER:
            if slot in ("hair_back", "body"):
                continue
            if slot in layer_imgs:
                canvas = Image.alpha_composite(canvas, layer_imgs[slot])

        outputs = {"layers": {}, "composite": None}
        for slot in ordered_slots:
            dest = out / f"layer_{direction}_{slot}.png"
            layer_imgs[slot].save(dest)
            outputs["layers"][slot] = {
                "filename": dest.name, "sha256": _sha256_file(dest)}
        composite_path = out / f"worn_{direction}.png"
        canvas.save(composite_path)
        outputs["composite"] = {
            "filename": composite_path.name,
            "sha256": _sha256_file(composite_path)}
        entry["outputs"] = outputs
        entry["status"] = "ok"
        manifest["summary"]["ok"] += 1
        manifest["entries"].append(entry)

    manifest_path = out / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8")
    manifest["manifest_filename"] = manifest_path.name
    return manifest
