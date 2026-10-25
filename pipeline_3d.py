"""
pipeline_3d.py - Plushy AI image-to-3D pipeline (rebuilt 2026-10-25).

Single image -> textured GLB, fully local on the Studio PC's GPU.
Backend: Stable Fast 3D (SF3D, stabilityai/stable-fast-3d), running in
its own virtualenv inside the Docker image (/opt/sf3d-venv, code pinned
at /opt/stable-fast-3d) and invoked as a subprocess, so its dependency
pins can never disturb the sprite pipeline's environment.

Why the rules below exist (Han, 2026-10-25): the first 3D path only ever
ran in mock mode and handed back a gray sphere placeholder; the real
model was never wired up, and the placeholder was not labelled loudly
enough to be recognised as fake. Therefore:

  - Mock output is produced ONLY when PLUSHY_MOCK=1. It is written to a
    *_MOCK.glb file name and carries a sidecar JSON stamped mock=true.
  - With mock off, a missing engine or a failed validation FAILS loudly.
    A placeholder is never substituted silently.
  - Every real output must pass validate_glb(): a real triangle count,
    a non-degenerate bounding box, and at least one texture image.
    A low-poly near-spherical result is rejected as a placeholder
    signature.

Usage:
    from pipeline_3d import Model3DPipeline, Model3DOptions
    pipe = Model3DPipeline()
    path, stats = pipe.image_to_glb("house.png", Path("out.glb"))
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("plushy.model3d")

MOCK = os.getenv("PLUSHY_MOCK", "0") == "1"
SF3D_PYTHON = Path(os.getenv("PLUSHY_SF3D_PYTHON", "/opt/sf3d-venv/bin/python"))
SF3D_HOME = Path(os.getenv("PLUSHY_SF3D_HOME", "/opt/stable-fast-3d"))
SF3D_MODEL = os.getenv("PLUSHY_3D_MODEL", "stabilityai/stable-fast-3d")

ProgressCallback = Callable[[float, str], None]


@dataclass
class Model3DOptions:
    texture_resolution: int = 1024   # 512 | 1024 | 2048
    remesh: str = "none"             # none | triangle | quad
    foreground_ratio: float = 0.85


def engine_installed() -> bool:
    return SF3D_PYTHON.exists() and (SF3D_HOME / "run.py").exists()


# ---------------------------------------------------------------------------
# GLB inspection (pure python: header + JSON chunk only)
# ---------------------------------------------------------------------------

def glb_stats(path: Path) -> dict:
    """Read triangle count, bbox and texture count from a GLB file."""
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError("not a GLB file (bad magic)")
    json_len = struct.unpack("<I", data[12:16])[0]
    gltf = json.loads(data[20:20 + json_len])

    accessors = gltf.get("accessors", [])
    tris = 0
    mins = [math.inf, math.inf, math.inf]
    maxs = [-math.inf, -math.inf, -math.inf]
    for mesh in gltf.get("meshes", []):
        for prim in mesh.get("primitives", []):
            if prim.get("mode", 4) != 4:
                continue
            pos = accessors[prim["attributes"]["POSITION"]]
            if "min" in pos and "max" in pos:
                for i in range(3):
                    mins[i] = min(mins[i], pos["min"][i])
                    maxs[i] = max(maxs[i], pos["max"][i])
            if "indices" in prim:
                tris += accessors[prim["indices"]]["count"] // 3
            else:
                tris += pos["count"] // 3
    extents = [round(maxs[i] - mins[i], 4) for i in range(3)] if tris else [0, 0, 0]
    return {
        "bytes": len(data),
        "triangles": tris,
        "meshes": len(gltf.get("meshes", [])),
        "images": len(gltf.get("images", [])),
        "bbox_extents": extents,
    }


def validate_glb(path: Path) -> dict:
    """Gate real outputs. Raises ValueError on a placeholder signature."""
    stats = glb_stats(path)
    if stats["bytes"] < 50_000:
        raise ValueError(f"GLB suspiciously small ({stats['bytes']} bytes)")
    if stats["triangles"] < 2000:
        raise ValueError(f"GLB has too few triangles ({stats['triangles']}) - placeholder signature")
    if stats["images"] < 1:
        raise ValueError("GLB has no texture image - expected a textured model")
    ext = stats["bbox_extents"]
    if min(ext) <= 0.02:
        raise ValueError(f"GLB bounding box is degenerate ({ext})")
    ratio = max(ext) / max(min(ext), 1e-6)
    if ratio < 1.15 and stats["triangles"] < 5000:
        raise ValueError(f"GLB looks like a plain sphere (extents {ext}, {stats['triangles']} tris)")
    return stats


# ---------------------------------------------------------------------------
# Mock placeholder (ONLY reachable with PLUSHY_MOCK=1, always stamped)
# ---------------------------------------------------------------------------

def _write_mock_sphere(dest: Path) -> Path:
    actual = dest.with_name(dest.stem + "_MOCK" + dest.suffix)
    lon_n, lat_n, r = 24, 16, 0.5
    positions, normals, indices = [], [], []
    for la in range(lat_n + 1):
        theta = math.pi * la / lat_n
        for lo in range(lon_n + 1):
            phi = 2 * math.pi * lo / lon_n
            x = r * math.sin(theta) * math.cos(phi)
            y = r * math.cos(theta)
            z = r * math.sin(theta) * math.sin(phi)
            positions += [x, y, z]
            normals += [x / r, y / r, z / r]
    for la in range(lat_n):
        for lo in range(lon_n):
            a = la * (lon_n + 1) + lo
            b = a + lon_n + 1
            indices += [a, b, a + 1, b, b + 1, a + 1]
    bin_data = struct.pack("<%df" % len(positions), *positions)
    bin_data += struct.pack("<%df" % len(normals), *normals)
    bin_data += struct.pack("<%dI" % len(indices), *indices)
    pos_bytes = 4 * len(positions)
    nrm_bytes = 4 * len(normals)
    gltf = {
        "asset": {"version": "2.0", "generator": "Plushy AI MOCK placeholder",
                  "extras": {"plushy_mock": True}},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "MOCK sphere placeholder - NOT a real model"}],
        "meshes": [{"primitives": [{
            "attributes": {"POSITION": 0, "NORMAL": 1},
            "indices": 2,
            "material": 0,
        }]}],
        "materials": [{"pbrMetallicRoughness": {
            "baseColorFactor": [0.6, 0.6, 0.62, 1.0],
            "metallicFactor": 0.0, "roughnessFactor": 0.9}}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(positions) // 3,
             "type": "VEC3", "min": [-r, -r, -r], "max": [r, r, r]},
            {"bufferView": 1, "componentType": 5126, "count": len(normals) // 3, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5125, "count": len(indices), "type": "SCALAR"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": pos_bytes},
            {"buffer": 0, "byteOffset": pos_bytes, "byteLength": nrm_bytes},
            {"buffer": 0, "byteOffset": pos_bytes + nrm_bytes, "byteLength": 4 * len(indices)},
        ],
        "buffers": [{"byteLength": len(bin_data)}],
    }
    json_data = json.dumps(gltf).encode()
    json_data += b" " * (-len(json_data) % 4)
    bin_data += b"\x00" * (-len(bin_data) % 4)
    total = 12 + 8 + len(json_data) + 8 + len(bin_data)
    with open(actual, "wb") as f:
        f.write(b"glTF" + struct.pack("<II", 2, total))
        f.write(struct.pack("<I", len(json_data)) + b"JSON" + json_data)
        f.write(struct.pack("<I", len(bin_data)) + b"BIN\x00" + bin_data)
    return actual


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class Model3DPipeline:
    def __init__(self):
        self.mock = MOCK

    def image_to_glb(self, image_path, dest: Path, options: Optional[Model3DOptions] = None,
                     progress: Optional[ProgressCallback] = None) -> tuple[Path, dict]:
        """Convert one image to a textured GLB at dest.

        Returns (actual_path, stats). In mock mode the actual path is a
        *_MOCK.glb and stats carry mock=true. Real failures raise.
        """
        options = options or Model3DOptions()
        progress = progress or (lambda p, m: None)
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"input image not found: {image_path}")

        if self.mock:
            progress(0.5, "MOCK mode: writing stamped placeholder (NOT a real model)")
            actual = _write_mock_sphere(dest)
            stats = {"mock": True, "engine": "mock", **glb_stats(actual)}
            _write_sidecar(actual, stats)
            progress(1.0, "MOCK placeholder done")
            return actual, stats

        if not engine_installed():
            raise RuntimeError(
                "SF3D engine is not installed in this image "
                f"(python={SF3D_PYTHON}, home={SF3D_HOME}). "
                "Rebuild the Docker image with the current Dockerfile, "
                "then start the Studio again. No placeholder was produced.")

        tex = options.texture_resolution
        if tex not in (512, 1024, 2048):
            tex = 1024
        remesh = options.remesh if options.remesh in ("none", "triangle", "quad") else "none"

        tmp = Path(tempfile.mkdtemp(prefix="plushy3d_"))
        try:
            progress(0.1, "SF3D reconstruction starting (first run downloads the model, ~3GB)")
            cmd = [
                str(SF3D_PYTHON), str(SF3D_HOME / "run.py"), str(image_path),
                "--output-dir", str(tmp),
                "--texture-resolution", str(tex),
                "--remesh_option", remesh,
                "--foreground-ratio", str(options.foreground_ratio),
                "--pretrained-model", SF3D_MODEL,
            ]
            env = dict(os.environ, PYTHONUNBUFFERED="1")
            proc = subprocess.run(cmd, cwd=str(SF3D_HOME), capture_output=True,
                                  text=True, timeout=1800, env=env)
            if proc.returncode != 0:
                tail = (proc.stderr or proc.stdout or "")[-1500:]
                raise RuntimeError(f"SF3D failed (exit {proc.returncode}): {tail}")
            produced = tmp / "0" / "mesh.glb"
            if not produced.exists():
                found = sorted(tmp.rglob("*.glb"))
                if not found:
                    raise RuntimeError("SF3D finished but produced no GLB file")
                produced = found[0]
            progress(0.85, "validating model (real-mesh gate)")
            stats = validate_glb(produced)
            stats.update({"mock": False, "engine": "sf3d", "model": SF3D_MODEL,
                          "texture_resolution": tex})
            shutil.copyfile(produced, dest)
            _write_sidecar(dest, stats)
            progress(1.0, "done")
            log.info("model3d done: %s (%s)", dest, stats)
            return dest, stats
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def _write_sidecar(glb_path: Path, stats: dict) -> None:
    sidecar = glb_path.with_name(glb_path.name + ".json")
    sidecar.write_text(json.dumps(stats, indent=2), encoding="utf-8")
