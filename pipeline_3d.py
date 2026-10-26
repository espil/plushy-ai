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
import time
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
    texture_resolution: int = 1024   # 512 | 1024 | 2048 (spec: <=1024 per building)
    remesh: str = "none"             # none | triangle | quad
    foreground_ratio: float = 0.85
    # Building spec (Han, 2026-10-25; asset standard v1): low-poly geometry
    # with real textures - normal buildings <= 8000 triangles, landmarks
    # <= 20000, then gltfpack (meshopt) compression. Enforced in post.
    tri_budget: int = 8000


def engine_installed() -> bool:
    return SF3D_PYTHON.exists() and (SF3D_HOME / "run.py").exists()


# ---------------------------------------------------------------------------
# Asset prefetch: SF3D silently downloads THREE things on first use -
# its own weights, facebook/dinov2-large (its image tokenizer reads it
# from the SF3D config), and rembg's u2net.onnx (from GitHub, into
# U2NET_HOME). Inside a piped subprocess those downloads are invisible
# and can crawl or stall for tens of minutes with the GPU idle - the
# exact failure Han hit on 2026-10-25 (50 silent minutes at "10%").
# So: fetch everything up front, in the open, verify the cache is
# complete, and then run SF3D with HF_HUB_OFFLINE=1 so it can never
# touch the network again. A missing file then fails instantly and
# names itself instead of hanging.
# ---------------------------------------------------------------------------

PREFETCH_REPOS = [SF3D_MODEL, "facebook/dinov2-large"]


def _hub_dir() -> Path:
    hf_home = os.getenv("HF_HOME")
    if hf_home:
        return Path(hf_home) / "hub"
    return Path(os.path.expanduser("~/.cache/huggingface")) / "hub"


def _u2net_home() -> Path:
    return Path(os.getenv("U2NET_HOME") or (_hub_dir().parent / "u2net"))


def _nvidia_lib_dirs() -> list[str]:
    """Library dirs onnxruntime's CUDA provider needs on the loader
    path (its .so links libcudnn/libcublas; if they are not findable,
    the CUDA provider silently drops out and rembg runs on CPU while
    onnxruntime logs a GPU-discovery warning - the exact warning Han
    flagged on 2026-10-25). torch's nvidia-* wheels carry the libs."""
    dirs = ["/usr/local/cuda/lib64"]
    site = SF3D_PYTHON.parent.parent / "lib" / "python3.10" / "site-packages"
    nvidia = site / "nvidia"
    if nvidia.exists():
        dirs += [str(p) for p in sorted(nvidia.glob("*/lib"))]
    return dirs


def _sf3d_env(offline: bool = False) -> dict:
    env = dict(os.environ, PYTHONUNBUFFERED="1",
               U2NET_HOME=str(_u2net_home()))
    libs = _nvidia_lib_dirs()
    if env.get("LD_LIBRARY_PATH"):
        libs.append(env["LD_LIBRARY_PATH"])
    env["LD_LIBRARY_PATH"] = ":".join(libs)
    if offline:
        env["HF_HUB_OFFLINE"] = "1"
    return env


def _repo_cache_state(repo_id: str) -> dict:
    folder = _hub_dir() / ("models--" + repo_id.replace("/", "--"))
    if not folder.exists():
        return {"exists": False, "snapshots": 0, "incomplete": 0, "bytes": 0}
    incomplete = len(list(folder.rglob("*.incomplete")))
    total = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
    snaps = list((folder / "snapshots").glob("*")) if (folder / "snapshots").exists() else []
    return {"exists": True, "snapshots": len(snaps),
            "incomplete": incomplete, "bytes": total}


def repo_cache_complete(repo_id: str) -> bool:
    st = _repo_cache_state(repo_id)
    return st["exists"] and st["snapshots"] > 0 and st["incomplete"] == 0


def ensure_assets_cached(progress: ProgressCallback = lambda p, m: None) -> None:
    """Download + verify every asset SF3D needs, with visible progress.
    Raises RuntimeError naming whatever could not be cached."""
    from huggingface_hub import snapshot_download

    for repo in PREFETCH_REPOS:
        if repo_cache_complete(repo):
            st = _repo_cache_state(repo)
            progress(0.04, f"model cache verified: {repo} "
                           f"({st['bytes'] / 1e6:.0f} MB, complete)")
            continue
        progress(0.04, f"downloading model: {repo} (visible, one-time)")
        snapshot_download(repo_id=repo)
        if not repo_cache_complete(repo):
            st = _repo_cache_state(repo)
            raise RuntimeError(
                f"model cache still incomplete for {repo}: {st}. "
                "Check the network connection to Hugging Face and retry.")
        st = _repo_cache_state(repo)
        progress(0.06, f"model cached: {repo} ({st['bytes'] / 1e6:.0f} MB)")

    u2net = _u2net_home() / "u2net.onnx"
    if u2net.exists():
        progress(0.06, "rembg u2net model verified in cache - probing providers")
    else:
        progress(0.06, "downloading rembg u2net model (one-time, ~170 MB)")
    # The probe prints which execution providers the live rembg session
    # actually binds - the GPU-discovery warning alone does not prove a
    # CPU fallback, and a CPU claim must be measured, not assumed.
    probe = (
        "import onnxruntime as ort, rembg;"
        "print('onnxruntime ' + ort.__version__);"
        "print('available providers: ' + str(ort.get_available_providers()));"
        "s = rembg.new_session();"
        "inner = getattr(s, 'inner_session', s);"
        "print('rembg session providers: ' + str(inner.get_providers()))"
    )
    rc, tail = _run_streaming(
        [str(SF3D_PYTHON), "-c", probe],
        cwd=str(SF3D_HOME), env=_sf3d_env(), timeout=1200, tag="prefetch")
    if rc != 0 or not u2net.exists():
        raise RuntimeError(
            f"rembg u2net download failed (exit {rc}): {tail[-800:]}")


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
            ensure_assets_cached(progress)
            progress(0.1, "SF3D reconstruction starting (assets cached, offline run)")
            cmd = [
                str(SF3D_PYTHON), str(SF3D_HOME / "run.py"), str(image_path),
                "--output-dir", str(tmp),
                "--texture-resolution", str(tex),
                "--remesh_option", remesh,
                "--foreground-ratio", str(options.foreground_ratio),
                "--pretrained-model", SF3D_MODEL,
            ]
            returncode, tail = _run_streaming(cmd, cwd=str(SF3D_HOME),
                                              env=_sf3d_env(offline=True),
                                              timeout=1800, tag="sf3d")
            if returncode != 0:
                raise RuntimeError(f"SF3D failed (exit {returncode}): {tail[-1500:]}")
            produced = tmp / "0" / "mesh.glb"
            if not produced.exists():
                found = sorted(tmp.rglob("*.glb"))
                if not found:
                    raise RuntimeError("SF3D finished but produced no GLB file")
                produced = found[0]
            progress(0.8, "validating model (real-mesh gate)")
            validate_glb(produced)
            progress(0.88, "low-poly + gltfpack pass (building spec)")
            final = self._postprocess(produced, tmp, options)
            stats = validate_glb(final)
            if stats["triangles"] > int(options.tri_budget * 1.05):
                raise ValueError(
                    f"post-processed GLB still over the triangle budget: "
                    f"{stats['triangles']} > {options.tri_budget}")
            stats.update({"mock": False, "engine": "sf3d", "model": SF3D_MODEL,
                          "texture_resolution": tex,
                          "tri_budget": options.tri_budget, "gltfpack": True})
            shutil.copyfile(final, dest)
            _write_sidecar(dest, stats)
            progress(1.0, "done")
            log.info("model3d done: %s (%s)", dest, stats)
            return dest, stats
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


    def _postprocess(self, produced: Path, tmp: Path, options: Model3DOptions) -> Path:
        """Enforce the building spec: decimate to the triangle budget with
        gltfpack's simplifier, then meshopt-compress (-c). Textures stay
        real (baked at <=1024 by SF3D). Fails loudly if gltfpack is absent."""
        gltfpack = os.getenv("PLUSHY_GLTFPACK") or shutil.which("gltfpack")
        if not gltfpack:
            raise RuntimeError(
                "gltfpack is not installed in this image, so the building "
                "spec (low-poly + meshopt compression) cannot be applied. "
                "Rebuild the Docker image with the current Dockerfile. "
                "No unprocessed model was delivered.")
        raw = glb_stats(produced)
        packed = tmp / "packed.glb"
        cmd = [gltfpack, "-i", str(produced), "-o", str(packed), "-c"]
        if raw["triangles"] > options.tri_budget:
            ratio = max(0.01, min(1.0, options.tri_budget / raw["triangles"] * 0.95))
            cmd += ["-si", f"{ratio:.3f}"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if proc.returncode != 0 or not packed.exists():
            tail = (proc.stderr or proc.stdout or "")[-1200:]
            raise RuntimeError(f"gltfpack failed (exit {proc.returncode}): {tail}")
        return packed


def _run_streaming(cmd, cwd, env, timeout, tag="sf3d"):
    """Run a subprocess with its output streamed live to our stdout
    (each line prefixed), keeping the tail for error reports. A silent
    capture_output run once hid a 30-minute stall completely - with
    streaming, a stuck download or a CPU fallback is visible as it
    happens, and even a timeout reports the last thing the child said."""
    import collections
    import threading

    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    tail: collections.deque = collections.deque(maxlen=80)
    state = {"last_line": time.monotonic(), "start": time.monotonic()}

    def reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            tail.append(line)
            state["last_line"] = time.monotonic()
            print(f"[{tag}] {line}", flush=True)

    def heartbeat() -> None:
        while proc.poll() is None:
            time.sleep(30)
            silence = time.monotonic() - state["last_line"]
            if silence >= 60 and proc.poll() is None:
                elapsed = time.monotonic() - state["start"]
                print(f"[{tag}] ... still running "
                      f"({elapsed:.0f}s elapsed, no output for {silence:.0f}s)",
                      flush=True)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    threading.Thread(target=heartbeat, daemon=True).start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        t.join(timeout=5)
        raise RuntimeError(
            f"{tag} timed out after {timeout}s. Last output:\n"
            + "\n".join(tail)[-1500:])
    t.join(timeout=5)
    return proc.returncode, "\n".join(tail)


def _write_sidecar(glb_path: Path, stats: dict) -> None:
    sidecar = glb_path.with_name(glb_path.name + ".json")
    sidecar.write_text(json.dumps(stats, indent=2), encoding="utf-8")
