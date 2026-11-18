"""Aseprite Bridge / Export for Plushy-AI 2.0 (Phase 5).

Packages already-generated PNG layers and per-direction PNGs into an
export directory with pre-export validation and a versioned export
manifest:

  - PNG copies of every input (bytes copied verbatim; originals are
    read-only and never modified)
  - one PNG sprite sheet (see exporter/sheet.py for the grid layout)
  - optionally, one layered .aseprite written by
    exporter/aseprite_write.py and verified by round-tripping it
    through the Phase 1 analyzer before the export is reported
  - export_manifest.json (schema 1.0)

Validation mirrors Phase 4's accounting style: every direction is
always accounted for (ok / missing / needs_review), every layer is
listed, and a size mismatch or a missing alpha channel marks the item
needs_review with the measured facts - nothing is silently dropped
and nothing is resized to fit.

When a source Aseprite standard record (Phase 1 JSON) is supplied,
the manifest preserves the linkage: the record is embedded in full
and its sha256 is recorded, so the original's analyzed metadata
travels with the export.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from asset_standard import analyze_file

from .aseprite_write import AsepriteWriteError, write_aseprite
from .sheet import DIRECTIONS, SHEET_COLUMNS, SHEET_ROWS, pack_sprite_sheet

MANIFEST_SCHEMA_VERSION = "1.0"
MANIFEST_NAME = "export_manifest.json"

__all__ = [
    "DIRECTIONS", "MANIFEST_SCHEMA_VERSION", "ExportError",
    "export_assets", "validate_image",
]


class ExportError(Exception):
    """Raised for invalid export requests (no inputs, bad paths, ...)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def _safe_name(name: str) -> str:
    safe = re.sub(r"[^a-z0-9_-]+", "_", str(name).lower()).strip("_")
    return safe or "layer"


def validate_image(path) -> dict:
    """Measure one PNG via the Phase 1 analyzer; return a facts dict."""
    path = Path(path)
    std = analyze_file(path)
    canvas = std["canvas"]
    return {
        "filename": path.name,
        "sha256": std["source"]["sha256"],
        "size_bytes": std["source"]["size_bytes"],
        "width": canvas["width"],
        "height": canvas["height"],
        "color_mode": canvas["color_mode"],
        "has_alpha": canvas["has_alpha"],
        "content_bounds": std["content_bounds"],
        "analysis_warnings": list(std["validation"]["warnings"]),
    }


def _item_status(facts: dict, expected_size, warnings: list) -> str:
    if expected_size is not None and \
            (facts["width"], facts["height"]) != tuple(expected_size):
        warnings.append(
            f"size mismatch: image is {facts['width']}x{facts['height']}, "
            f"expected {expected_size[0]}x{expected_size[1]}; "
            f"not resized, not packed")
    if not facts["has_alpha"]:
        warnings.append("image has no alpha channel")
    if facts["content_bounds"] is None:
        warnings.append("image is fully transparent (no content bounds)")
    return "needs_review" if warnings else "ok"


def export_assets(out_dir, direction_images=None, layers=None,
                  source_standard=None, aseprite_name=None,
                  sheet_name="sprite_sheet.png",
                  asset_id="export") -> dict:
    """Run an export and return the manifest dict (also written to disk).

    direction_images: {direction: png_path} for any subset of the 8
        canonical directions; absent directions are recorded missing.
    layers: [(name, png_path), ...] named layers for PNG copies and,
        when `aseprite_name` is given, the layered .aseprite (layer
        order preserved, bottom-to-top).
    source_standard: optional path to a Phase 1 asset-standard JSON
        (e.g. the analysis of a source .aseprite); embedded in full
        in the manifest with its sha256.
    aseprite_name: optional filename for the layered .aseprite output.
        When layers are missing/mismatched, the .aseprite is not
        written and the manifest records why (status needs_review).

    Raises ExportError when neither directions nor layers are given,
    or an input path does not exist.
    """
    direction_images = dict(direction_images or {})
    layers = list(layers or [])
    if not direction_images and not layers:
        raise ExportError("nothing to export: no direction images and "
                          "no layers were given")
    for d, p in direction_images.items():
        if d not in DIRECTIONS:
            raise ExportError(f"unknown direction {d!r}; expected one "
                              f"of {', '.join(DIRECTIONS)}")
        if not Path(p).exists():
            raise ExportError(f"direction {d} image not found: {p}")
    for name, p in layers:
        if not Path(p).exists():
            raise ExportError(f"layer {name!r} image not found: {p}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "asset_id": _safe_name(asset_id),
        "created_at": _now(),
        "status": "ok",
        "source_standard": None,
        "directions": [],
        "layers": [],
        "outputs": {"png_copies": [], "sprite_sheet": None,
                    "aseprite": None},
        "validation": {"directions_ok": 0, "directions_missing": 0,
                       "directions_needs_review": 0,
                       "layers_ok": 0, "layers_needs_review": 0,
                       "warnings": []},
    }

    # --- source Aseprite metadata preservation -------------------------
    if source_standard is not None:
        sp = Path(source_standard)
        if not sp.exists():
            raise ExportError(f"source standard record not found: {sp}")
        raw = sp.read_bytes()
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ExportError(f"source standard record is not valid "
                              f"JSON: {e}") from e
        manifest["source_standard"] = {
            "filename": sp.name,
            "sha256": _sha256_bytes(raw),
            "asset_id": record.get("asset_id"),
            "schema_version": record.get("schema_version"),
            "source_filename": (record.get("source") or {}).get("filename"),
            "source_sha256": (record.get("source") or {}).get("sha256"),
            "record": record,
        }

    # --- direction accounting + validation -----------------------------
    # Only direction exports account directions: when a direction set
    # is given, all 8 are always listed (ok / missing / needs_review).
    # A layer-only export lists none - it claims no directions at all.
    # Expected canvas = the first present direction's size, in
    # canonical order; every other direction is measured against it.
    expected_size = None
    direction_facts = {}
    for d in DIRECTIONS:
        if d in direction_images:
            facts = validate_image(direction_images[d])
            direction_facts[d] = facts
            if expected_size is None:
                expected_size = (facts["width"], facts["height"])
    sheet_images = {}
    for d in (DIRECTIONS if direction_images else ()):
        if d not in direction_images:
            manifest["directions"].append(
                {"direction": d, "status": "missing", "packed": False,
                 "filename": None, "sha256": None, "width": None,
                 "height": None, "has_alpha": None,
                 "content_bounds": None, "warnings": []})
            manifest["validation"]["directions_missing"] += 1
            continue
        facts = direction_facts[d]
        warnings = list(facts["analysis_warnings"])
        status = _item_status(facts, expected_size, warnings)
        entry = {"direction": d, "status": status, "packed": False,
                 "filename": facts["filename"], "sha256": facts["sha256"],
                 "width": facts["width"], "height": facts["height"],
                 "has_alpha": facts["has_alpha"],
                 "content_bounds": facts["content_bounds"],
                 "warnings": warnings}
        manifest["directions"].append(entry)
        if status == "ok":
            manifest["validation"]["directions_ok"] += 1
        else:
            manifest["validation"]["directions_needs_review"] += 1
        # PNG copy (verbatim bytes) for every present direction.
        dest = out_dir / f"{d.lower()}.png"
        shutil.copyfile(direction_images[d], dest)
        manifest["outputs"]["png_copies"].append(dest.name)
        entry["exported_png"] = dest.name
        if status == "ok":
            from PIL import Image
            sheet_images[d] = Image.open(direction_images[d]).convert("RGBA")
            sheet_images[d].load()

    # --- sprite sheet ----------------------------------------------------
    if direction_images:
        sheet_path, placement = pack_sprite_sheet(
            sheet_images, expected_size, out_dir / sheet_name)
        for entry in manifest["directions"]:
            place = placement[entry["direction"]]
            entry["packed"] = place["packed"]
            entry["sheet_cell"] = place["cell"]
        manifest["outputs"]["sprite_sheet"] = {
            "filename": sheet_path.name,
            "sha256": _sha256_file(sheet_path),
            "width": SHEET_COLUMNS * expected_size[0],
            "height": SHEET_ROWS * expected_size[1],
            "layout": {"columns": SHEET_COLUMNS, "rows": SHEET_ROWS,
                       "order": list(DIRECTIONS),
                       "cell_width": expected_size[0],
                       "cell_height": expected_size[1]},
        }

    # --- layers: validation, PNG copies, optional .aseprite -------------
    layer_canvas = expected_size
    layer_facts = []
    for name, p in layers:
        facts = validate_image(p)
        if layer_canvas is None:
            layer_canvas = (facts["width"], facts["height"])
        warnings = list(facts["analysis_warnings"])
        status = _item_status(facts, layer_canvas, warnings)
        entry = {"name": name, "status": status,
                 "filename": facts["filename"], "sha256": facts["sha256"],
                 "width": facts["width"], "height": facts["height"],
                 "has_alpha": facts["has_alpha"],
                 "content_bounds": facts["content_bounds"],
                 "warnings": warnings}
        dest = out_dir / f"layer_{_safe_name(name)}.png"
        shutil.copyfile(p, dest)
        manifest["outputs"]["png_copies"].append(dest.name)
        entry["exported_png"] = dest.name
        manifest["layers"].append(entry)
        layer_facts.append((name, p, status))
        if status == "ok":
            manifest["validation"]["layers_ok"] += 1
        else:
            manifest["validation"]["layers_needs_review"] += 1

    if aseprite_name is not None:
        ase_entry = {"filename": aseprite_name, "status": None,
                     "reason": None, "sha256": None, "roundtrip": None}
        bad = [n for n, _p, s in layer_facts if s != "ok"]
        if not layers:
            ase_entry["status"] = "needs_review"
            ase_entry["reason"] = "no layers were given for the .aseprite"
        elif bad:
            ase_entry["status"] = "needs_review"
            ase_entry["reason"] = ("layers not ok (missing alpha, size "
                                   "mismatch or empty): " + ", ".join(bad))
        else:
            from PIL import Image
            pil_layers = []
            for name, p, _s in layer_facts:
                img = Image.open(p)
                img.load()
                pil_layers.append((name, img.convert("RGBA")))
            try:
                ase_path = write_aseprite(out_dir / aseprite_name,
                                          pil_layers)
            except AsepriteWriteError as e:
                ase_entry["status"] = "needs_review"
                ase_entry["reason"] = f"writer refused: {e}"
            else:
                # Mandatory round-trip: re-analyze what we just wrote
                # with the Phase 1 analyzer and check the facts.
                std = analyze_file(ase_path)
                rt_layers = [layer["name"] for layer in std["layers"]]
                rt_cels = std["frames"][0]["cels"] if std["frames"] else []
                expected_names = [n for n, _p, _s in layer_facts]
                passed = (
                    rt_layers == expected_names
                    and std["canvas"]["width"] == layer_canvas[0]
                    and std["canvas"]["height"] == layer_canvas[1]
                    and len(std["frames"]) == 1
                    and len(rt_cels) == len(expected_names)
                    and all(c["width"] == layer_canvas[0]
                            and c["height"] == layer_canvas[1]
                            for c in rt_cels))
                ase_entry["roundtrip"] = {
                    "status": "passed" if passed else "failed",
                    "checker": "asset_standard.analyze_file (Phase 1)",
                    "layers": rt_layers,
                    "canvas": {"width": std["canvas"]["width"],
                               "height": std["canvas"]["height"]},
                    "frames": len(std["frames"]),
                    "cels": len(rt_cels),
                }
                if passed:
                    ase_entry["status"] = "ok"
                    ase_entry["sha256"] = _sha256_file(ase_path)
                else:
                    ase_entry["status"] = "needs_review"
                    ase_entry["reason"] = ("round-trip through the Phase 1 "
                                           "analyzer did not reproduce the "
                                           "expected layers/canvas/cels")
        manifest["outputs"]["aseprite"] = ase_entry

    # --- overall status ---------------------------------------------------
    v = manifest["validation"]
    v["warnings"] = [f"direction {e['direction']}: {w}"
                     for e in manifest["directions"] for w in e["warnings"]]
    v["warnings"] += [f"layer {e['name']}: {w}"
                      for e in manifest["layers"] for w in e["warnings"]]
    ase = manifest["outputs"]["aseprite"]
    if (v["directions_missing"] or v["directions_needs_review"]
            or v["layers_needs_review"]
            or (ase is not None and ase["status"] != "ok")):
        manifest["status"] = "needs_review"

    (out_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8")
    return manifest
