#!/usr/bin/env python3
"""Generate PLUSHY_ASSET_MANIFEST.json from ACTUAL deliverable files.

Scans the known production folders under the Zealandia goal files and
the plushy-ai prompt batches. An entry is emitted only when its file
exists; measurements (bytes, GLB triangles, PNG size) are read from
the file itself. Status/notes are editorial and live in OVERRIDES.

Usage: python3 gen_manifest.py [output_path]
"""
import json
import struct
import sys
from pathlib import Path

HOME = Path.home()
FILES = HOME / "workspace/goals/zealandia-game-project/files"
PROMPTS = HOME / "workspace/plushy-ai/prompts"


def glb_stats(path):
    d = path.read_bytes()
    jlen = struct.unpack("<I", d[12:16])[0]
    js = json.loads(d[20:20 + jlen])
    tris = 0
    for m in js.get("meshes", []):
        for p in m["primitives"]:
            if "indices" in p:
                tris += js["accessors"][p["indices"]]["count"] // 3
            else:
                tris += js["accessors"][p["attributes"]["POSITION"]]["count"] // 3
    anims = [a.get("name", "") for a in js.get("animations", [])]
    nodes = [n.get("name", "") for n in js.get("nodes", []) if "mesh" in n]
    return {"triangles": tris, "animations": anims, "nodes": nodes, "bytes": len(d)}


def png_size(path):
    from PIL import Image
    with Image.open(path) as im:
        return im.size


def entry(id_, name, type_, category, status, method, path, notes="", extra=None):
    e = {
        "id": id_,
        "name": name,
        "type": type_,
        "category": category,
        "status": status,
        "source": {"method": method},
        "visual": {"file": str(path).replace(str(HOME), "~"), "bytes": path.stat().st_size},
        "notes": notes,
    }
    if extra:
        e.update(extra)
    return e


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("PLUSHY_ASSET_MANIFEST.json")
    assets = []

    def add_glb(id_, name, category, status, path, notes="", height=None):
        if not path.exists():
            return
        st = glb_stats(path)
        m3d = {"triangles": st["triangles"], "animations": st["animations"],
               "nodeName": st["nodes"][0] if st["nodes"] else "", "pivot": "base-centre, ground y=0",
               "compressed": False}
        if height is not None:
            m3d["heightM"] = height
        e = entry(id_, name, "model3d", category, status, "meshy-i2i3d", path, notes,
                  {"model3d": m3d})
        e["visual"]["format"] = "glb"
        assets.append(e)

    add_glb("landmark_zealandia_timestone_01", "Time Stone", "landmark", "ready",
            FILES / "timestone-plushy/timestone.glb",
            "Wired into the game 2026-10-22 (optimized copy in payload). Master is uncompressed.", 5.52)
    for bid, label in [("b1_redbrick", "Auckland Street Building B1 Redbrick"),
                       ("b2_teal", "Auckland Street Building B2 Teal"),
                       ("b3_orange", "Auckland Street Building B3 Orange"),
                       ("b4_cafe", "Auckland Street Building B4 Cafe")]:
        h = 7.0 if bid == "b4_cafe" else 11.0
        add_glb(f"building_auckland_{bid}_01", label, "building", "ready",
                FILES / f"auckland-street-buildings/building_{bid}.glb",
                "Master, uncompressed; decimation + gltfpack required before production use.", h)
    add_glb("character_hermes_static_01", "Hermes (static)", "character", "ready",
            FILES / "boss-hermes/hermes.glb", "Boss, never aggroed by design.", 7.20)
    add_glb("character_hermes_animated_01", "Hermes (animated)", "character", "ready",
            FILES / "boss-hermes/hermes_animated.glb",
            "Clips: Idle, Walk, Run, Leap, WalkBasic, RunBasic.", 7.20)
    add_glb("character_lunaris_static_01", "Lunaris (static)", "character", "ready",
            FILES / "lunaris/lunaris.glb", "", 1.70)
    add_glb("character_lunaris_animated_01", "Lunaris (animated)", "character", "ready",
            FILES / "lunaris/lunaris_animated.glb",
            "Clips: Idle, Walk, TimeCast, Wave, WalkBasic, RunBasic. Wired into the game 2026-10-22.", 1.70)
    for g in ("male", "female"):
        for v in range(1, 5):
            p = FILES / f"character-retextures/{g}_v{v}.glb"
            if p.exists():
                e = entry(f"character_retexture_{g}_v{v}", f"Player {g} retexture v{v}",
                          "model3d", "character", "ready", "meshy-retexture", p,
                          "Texture-only variant of the original model; geometry/rig/animations byte-identical to the original. Han decision 2026-10-22: keep as-is.")
                e["visual"]["format"] = "glb"
                assets.append(e)
            pv = FILES / f"character-variants/{g}_v{v}/{g}_v{v}_animated.glb"
            if pv.exists():
                st = glb_stats(pv)
                e = entry(f"character_variant_{g}_v{v}", f"Generated variant {g} v{v} (NPC planned)",
                          "model3d", "character", "placeholder", "meshy-i2i3d", pv,
                          "Full-generation set superseded by the retextures for player use; Han decided 2026-10-22 to repurpose as NPCs.",
                          {"model3d": {"triangles": st["triangles"], "animations": st["animations"],
                                       "heightM": 1.70, "pivot": "base-centre, ground y=0", "compressed": False}})
                e["visual"]["format"] = "glb"
                assets.append(e)
    add_glb("character_lf2_firen_01", "LF2 Firen (modern outfit)", "character", "ready",
            FILES / "lf2-characters/firen.glb", "Static master, uncompressed.", 1.70)
    add_glb("character_lf2_frozen_01", "LF2 Frozen (modern outfit)", "character", "ready",
            FILES / "lf2-characters/frozen.glb", "Static master, uncompressed.", 1.70)

    ms = FILES / "monster-sprites"
    if ms.exists():
        frames = list((ms / "frames").glob("*.png")) if (ms / "frames").exists() else []
        for sheet in sorted(ms.glob("*_sheet.png")) + sorted(ms.glob("*_walk_sheet.png")):
            w, h = png_size(sheet)
            e = entry(f"monster_sheet_{sheet.stem}", f"Monster sheet {sheet.stem}", "sprite_sheet",
                      "monster", "ready", "plushy-sdxl", sheet,
                      "Wired into the game 2026-10-23.")
            e["visual"].update({"format": "png", "widthPx": w, "heightPx": h, "transparent": False, "view": "sheet"})
            assets.append(e)
        if frames:
            e = entry("monster_frames_pack_01", "Monster sprite frames (extracted)", "sprite2d",
                      "monster", "ready", "plushy-sdxl", ms / "frames",
                      f"{len(frames)} transparent PNG frames, bottom-centre anchor.")
            e["visual"] = {"file": str(ms / "frames").replace(str(HOME), "~"), "format": "png", "transparent": True}
            assets.append(e)

    for pf, label, note in [
        ("vancouver_buildings.txt", "Vancouver buildings prompt batch", "Outputs approved by Han 2026-10-11 (validated reference set)."),
        ("vancouver_props.txt", "Vancouver props prompt batch", ""),
        ("tokyo_buildings.txt", "Tokyo buildings prompt batch", "Generation on Han's GPU PC pending."),
        ("tokyo_props.txt", "Tokyo props prompt batch", "Generation on Han's GPU PC pending."),
        ("tokyo_archetypes.txt", "Tokyo archetypes prompt batch", "Generation on Han's GPU PC pending."),
        ("timestone.txt", "Time Stone prompt batch", "Produced via room pipeline; prompts retained."),
        ("zealandia_facilities_buildings.txt", "Zealandia facility buildings prompt batch (front view)", "Generation on Han's GPU PC pending."),
        ("zealandia_facilities_props.txt", "Zealandia facility props prompt batch (front view)", "Generation on Han's GPU PC pending."),
        ("everplanet_waitemata_buildings.txt", "EverPlanet-pack Waitemata buildings prompt batch", "Zealandia room production pack e4e8ac8; generation on Han's GPU PC."),
        ("everplanet_waitemata_props.txt", "EverPlanet-pack Waitemata props prompt batch", "Zealandia room production pack e4e8ac8."),
        ("everplanet_characters.txt", "EverPlanet-pack characters prompt batch", "Zealandia room production pack e4e8ac8."),
        ("everplanet_dungeon_entrances.txt", "EverPlanet-pack dungeon entrances prompt batch", "Zealandia room production pack e4e8ac8."),
        ("everplanet_dungeon_assets.txt", "EverPlanet-pack dungeon assets prompt batch", "Zealandia room production pack e4e8ac8."),
    ]:
        p = PROMPTS / pf
        if p.exists():
            e = entry(f"promptbatch_{pf.replace('.txt', '')}", label, "prompt_batch", "facility",
                      "ready", "plushy-sdxl", p, note)
            e["visual"]["format"] = "png"
            assets.append(e)

    fx = HOME / "workspace/plushy-ai/run_skill_fx.py"
    if fx.exists():
        e = entry("promptbatch_skill_fx", "Skill FX prompt batch (39 prompts + runner)", "prompt_batch",
                  "effect", "ready", "plushy-sdxl", fx, "Generation on Han's GPU PC.")
        e["visual"]["format"] = "png"
        assets.append(e)

    doc = {
        "manifest": "plushy-asset-manifest/v1",
        "standard": "docs/standard/PLUSHY_PRODUCTION_STANDARD.md",
        "schema": "docs/standard/PLUSHY_ASSET_SCHEMA.json",
        "note": "Generated from actual files by gen_manifest.py. An asset whose file does not exist never appears here. Masters are uncompressed unless model3d.compressed is true.",
        "assets": assets,
    }
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    print(f"wrote {out}: {len(assets)} assets")
    from collections import Counter
    print(Counter(a['status'] for a in assets))


if __name__ == "__main__":
    main()
