#!/usr/bin/env python3
"""
citygen.py — replicate a city's buildings as 3D GLBs.

Takes OSM building footprints + heights and produces one GLB per map chunk,
ready to load in a game engine. Two modes that compose:

  1. Procedural (no AI needed): every building extruded from its footprint.
     Whole city in minutes. Run this TODAY.
  2. AI archetypes: buildings are classified into ~12 archetypes
     (height band x footprint size). Generate one detailed 3D building per
     archetype with Plushy AI, drop the GLBs in --archetypes, and citygen
     fits each AI building onto every matching footprint (scaled to fit).

Typical workflow:
  # see what archetypes your city needs (and how many of each):
  python citygen.py --osm vancouver.geojson --list-archetypes

  # build the full procedural city:
  python citygen.py --osm vancouver.geojson --out city/

  # generate archetype reference images -> Plushy batch -> archetype_<id>.glb,
  # put them in ai/, then rebuild with AI buildings:
  python citygen.py --osm vancouver.geojson --out city_ai/ --archetypes ai/

Input GeoJSON: features with Polygon geometry (WGS84 lng/lat) and properties
  height (meters) and/or building:levels. Use --center to set the projection
  origin (defaults to downtown Vancouver). If your coordinates are already in
  local meters, pass --meters.

Output: <out>/<chunk_id>.glb + manifest.json
  chunk_id looks like "c3_-2" (250m grid cells).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

try:
    import trimesh
except ImportError:
    sys.exit("trimesh is required: pip install trimesh numpy")


DEFAULT_CENTER = (49.2827, -123.1207)  # Canada Place, Vancouver
CHUNK = 250.0


# ---------------------------------------------------------------- input

def project(lng: float, lat: float, center) -> tuple[float, float]:
    """Equirectangular lng/lat -> local meters (x east, z south... flipped to -z north below)."""
    clat, clng = center
    x = (lng - clng) * 111320.0 * math.cos(math.radians(clat))
    z = -(lat - clat) * 110540.0  # -z = north, matches engine convention
    return x, z


def load_buildings(path: Path, center, use_meters: bool, limit: int = 0):
    data = json.loads(path.read_text())
    feats = data["features"] if isinstance(data, dict) and "features" in data else data
    out = []
    for f in feats:
        g = f.get("geometry") or {}
        if g.get("type") != "Polygon":
            continue
        ring = g["coordinates"][0]
        if use_meters:
            pts = [(float(x), float(z)) for x, z in ring]
        else:
            pts = [project(float(x), float(y), center) for x, y in ring]
        # drop duplicate closing point
        if len(pts) > 1 and pts[0] == pts[-1]:
            pts = pts[:-1]
        if len(pts) < 3:
            continue
        props = f.get("properties") or {}
        height = props.get("height")
        try:
            height = float(height) if height is not None else None
        except (TypeError, ValueError):
            height = None
        if height is None:
            levels = props.get("building:levels") or props.get("levels")
            try:
                height = float(levels) * 3.2 if levels else None
            except (TypeError, ValueError):
                height = None
        btype = str(props.get("building") or "yes")
        if height is None or height <= 0:
            # sensible defaults by type
            height = 8.0 if btype in ("house", "residential", "apartments") else 15.0
        out.append({"pts": pts, "height": float(height), "type": btype})
        if limit and len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- archetypes

def poly_area(pts) -> float:
    p = np.asarray(pts, float)
    return abs(float(np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1])) / 2.0)


def classify(b) -> str:
    h = b["height"]
    a = poly_area(b["pts"])
    band = "house" if h < 12 else "lowrise" if h < 25 else "midrise" if h < 50 else "tower"
    size = "small" if a < 400 else "medium" if a < 2000 else "large"
    return f"{band}_{size}"


# ---------------------------------------------------------------- geometry

def extrude_footprint(pts, height) -> "trimesh.Trimesh":
    """Extrude a footprint polygon straight up. Flat roof (v1)."""
    p = np.asarray(pts, float)
    n = len(p)
    verts = [[x, 0.0, z] for x, z in p] + [[x, height, z] for x, z in p]
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.append([i, j, n + j])
        faces.append([i, n + j, n + i])
    # caps: triangle fan around centroid (exact for convex footprints)
    cx, cz = p[:, 0].mean(), p[:, 1].mean()
    cb, ct = len(verts), len(verts) + 1
    verts.append([cx, 0.0, cz])
    verts.append([cx, height, cz])
    for i in range(n):
        j = (i + 1) % n
        faces.append([cb, j, i])
        faces.append([ct, n + i, n + j])
    m = trimesh.Trimesh(np.array(verts), np.array(faces), process=True)
    return m


def load_archetype(path: Path) -> "trimesh.Trimesh":
    obj = trimesh.load(path, force="scene")
    if isinstance(obj, trimesh.Scene):
        # apply scene transforms, merge into one mesh
        dumped = obj.dump(concatenate=True)
        mesh = dumped
        if not isinstance(mesh, trimesh.Trimesh):
            geoms = [g for g in obj.geometry.values() if isinstance(g, trimesh.Trimesh)]
            mesh = trimesh.util.concatenate(tuple(geoms))
    else:
        mesh = obj
    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError(f"{path}: no mesh geometry found")
    return mesh


def fit_archetype(src: "trimesh.Trimesh", pts, height) -> "trimesh.Trimesh":
    """Scale/translate an archetype GLB to fit a footprint + height."""
    p = np.asarray(pts, float)
    smin, smax = src.bounds
    span = smax - smin
    span[span < 1e-6] = 1e-6
    tx0, tx1 = p[:, 0].min(), p[:, 0].max()
    tz0, tz1 = p[:, 1].min(), p[:, 1].max()
    target = np.array([tx1 - tx0, height, tz1 - tz0])
    target[target < 1e-6] = 1e-6
    m = src.copy()
    m.apply_translation(-(smin + smax) / 2.0)   # center on origin
    m.apply_scale(target / span)                # fit bbox
    m.apply_translation([(tx0 + tx1) / 2.0, 0.0, (tz0 + tz1) / 2.0])
    return m


# ---------------------------------------------------------------- build

def build_city(buildings, archetype_dir: Path | None):
    """Returns: dict chunk_id -> list of trimesh meshes, plus stats."""
    arch_cache: dict[str, "trimesh.Trimesh"] = {}
    chunks: dict[str, list] = {}
    stats = {"procedural": 0, "ai": 0, "archetypes_used": set(), "archetypes_missing": set()}

    def get_arch(aid):
        if aid in arch_cache:
            return arch_cache[aid]
        if archetype_dir:
            cand = archetype_dir / f"archetype_{aid}.glb"
            if cand.exists():
                try:
                    arch_cache[aid] = load_archetype(cand)
                    return arch_cache[aid]
                except Exception as e:
                    print(f"  warning: could not load {cand}: {e}", file=sys.stderr)
        arch_cache[aid] = None
        return None

    for b in buildings:
        aid = classify(b)
        mesh = None
        arch = get_arch(aid)
        if arch is not None:
            try:
                mesh = fit_archetype(arch, b["pts"], b["height"])
                stats["ai"] += 1
                stats["archetypes_used"].add(aid)
            except Exception as e:
                print(f"  warning: archetype {aid} fit failed: {e}", file=sys.stderr)
        if mesh is None:
            mesh = extrude_footprint(b["pts"], b["height"])
            stats["procedural"] += 1
            stats["archetypes_missing"].add(aid)
        cx = sum(x for x, _ in b["pts"]) / len(b["pts"])
        cz = sum(z for _, z in b["pts"]) / len(b["pts"])
        cid = f"c{math.floor(cx / CHUNK)}_{math.floor(cz / CHUNK)}"
        chunks.setdefault(cid, []).append(mesh)

    stats["archetypes_used"] = sorted(stats["archetypes_used"])
    stats["archetypes_missing"] = sorted(stats["archetypes_missing"])
    return chunks, stats


def export_chunks(chunks, outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    manifest = {"chunk_size": CHUNK, "chunks": []}
    ids = sorted(chunks)
    for i, cid in enumerate(ids):
        meshes = chunks[cid]
        try:
            merged = trimesh.util.concatenate(tuple(meshes))
        except Exception:
            merged = meshes[0]
        fn = f"{cid}.glb"
        merged.export(outdir / fn)
        xs = [m.bounds[0][0] for m in meshes]
        zs = [m.bounds[0][2] for m in meshes]
        manifest["chunks"].append({
            "id": cid, "file": fn, "buildings": len(meshes),
            "bounds": [min(xs), min(zs), max(xs), max(zs)],
        })
        print(f"  [{i + 1}/{len(ids)}] {fn}: {len(meshes)} buildings")
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


# ---------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(description="Replicate a city's buildings as chunked 3D GLBs.")
    ap.add_argument("--osm", required=True, help="GeoJSON with building footprints")
    ap.add_argument("--out", required=True, help="output directory for chunk GLBs")
    ap.add_argument("--center", default=",".join(map(str, DEFAULT_CENTER)),
                    help="projection origin lat,lng (default downtown Vancouver)")
    ap.add_argument("--meters", action="store_true",
                    help="coordinates already in local meters (skip projection)")
    ap.add_argument("--chunk", type=float, default=250.0, help="chunk size in meters")
    ap.add_argument("--archetypes", default=None,
                    help="dir with archetype_<id>.glb AI buildings")
    ap.add_argument("--list-archetypes", action="store_true",
                    help="print needed archetypes + counts, then exit")
    ap.add_argument("--limit", type=int, default=0, help="process first N buildings only (testing)")
    args = ap.parse_args()

    global CHUNK
    CHUNK = args.chunk
    center = tuple(map(float, args.center.split(",")))
    buildings = load_buildings(Path(args.osm), center, args.meters, args.limit)
    print(f"loaded {len(buildings)} buildings from {args.osm}")
    if not buildings:
        sys.exit("no buildings found — check the GeoJSON format")

    if args.list_archetypes:
        from collections import Counter
        counts = Counter(classify(b) for b in buildings)
        print(f"\n{len(counts)} archetypes needed (generate one GLB per archetype with Plushy AI):\n")
        for aid, n in counts.most_common():
            print(f"  archetype_{aid}.glb  x{n:6d} buildings")
        print("\nGenerate with Plushy batch: one reference image per archetype -> "
              "batch.py -> rename output to archetype_<id>.glb")
        return

    archdir = Path(args.archetypes) if args.archetypes else None
    chunks, stats = build_city(buildings, archdir)
    print(f"\nassembling {len(chunks)} chunks "
          f"({stats['ai']} AI / {stats['procedural']} procedural buildings)...")
    manifest = export_chunks(chunks, Path(args.out))
    print(f"\ndone: {len(buildings)} buildings -> {len(chunks)} chunks in {args.out}")
    print(f"  AI: {stats['procedural'] and stats['ai']} buildings "
          f"({len(stats['archetypes_used'])} archetypes)")
    if stats["archetypes_missing"] and archdir:
        print(f"  missing AI archetypes (fell back to procedural): "
              f"{', '.join(stats['archetypes_missing'])}")
    print(f"  manifest -> {args.out}/manifest.json")


if __name__ == "__main__":
    main()
