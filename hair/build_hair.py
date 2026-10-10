#!/usr/bin/env python3
"""Build a low-poly hair mesh fitted to the female character's head.

Derived from her head measurements (Drive: female.glb):
  head centroid ~ (-0.002, 0.584, 0.067), head radii ~ (0.60, 0.33, 0.44)
  facing: -X (determined from renders)
Style: white/silver voluminous bob, face opening at front, bangs, ahoge.
"""
import numpy as np
import trimesh

# --- head form (measured) ---
HC = np.array([-0.002, 0.584, 0.067])   # head centroid
HR = np.array([0.60, 0.33, 0.44])        # head radii (x, y, z)
FRONT = np.array([-1.0, 0.0, 0.0])       # facing direction

HAIR_TOP = np.array([235, 235, 242])     # silvery white
HAIR_TIP = np.array([205, 205, 215])     # slightly darker at tips


def paint(mesh, c_top=HAIR_TOP, c_tip=HAIR_TIP):
    """Vertical gradient vertex colors."""
    y = mesh.vertices[:, 1]
    t = (y - y.min()) / max(y.max() - y.min(), 1e-9)
    cols = (c_tip[None, :] * (1 - t[:, None]) + c_top[None, :] * t[:, None])
    mesh.visual = trimesh.visual.ColorVisuals(
        mesh, vertex_colors=np.column_stack(
            [cols, np.full(len(cols), 255)]).astype(np.uint8))
    return mesh


def build_cap():
    """Main hair shell: ellipsoid cap with face opening + bob flare."""
    sph = trimesh.creation.icosphere(subdivisions=3, radius=1.0)  # 1280 faces
    v = sph.vertices.copy()
    # scale to hair radii (head * 1.16, a bit taller)
    R = HR * np.array([1.16, 1.22, 1.16])
    v *= R
    v += HC + np.array([0.03, 0.06, 0.0])  # sit slightly up/back
    # bob flare: push lower verts outward in x/z
    ynorm = (v[:, 1] - v[:, 1].min()) / (v[:, 1].max() - v[:, 1].min())
    flare = 1.0 + 0.38 * np.clip(1 - ynorm * 2.0, 0, 1)
    c = HC + np.array([0.03, 0.0, 0.0])
    v[:, 0] = c[0] + (v[:, 0] - c[0]) * flare
    v[:, 2] = c[2] + (v[:, 2] - c[2]) * flare
    sph.vertices = v
    # cut face opening: front (-X) and below mid-height
    vl = v - (HC + np.array([0.03, 0.06, 0.0]))
    keep = ~((vl[:, 0] < -0.18) & (vl[:, 1] < 0.16))
    # also trim the very bottom rim all around (keep bob above shoulders)
    keep &= (vl[:, 1] > -R[1] * 0.92)
    cap = sph.submesh([np.where(keep[sph.faces].all(axis=1))[0]], append=True)
    return paint(cap)


def build_bangs():
    """Fringe band across the forehead, top edge tucked under the cap."""
    # top edge tucked INSIDE the cap shell; bottom jagged tips hang over forehead
    z = np.linspace(-0.36, 0.36, 11)
    x_top = -0.40 + 0.03 * np.cos(z / 0.36 * 1.2)
    y_top = HC[1] + 0.28 - 0.05 * (z / 0.36) ** 2
    jag = np.array([0.20, 0.12, 0.22, 0.10, 0.20, 0.11, 0.21, 0.12, 0.20, 0.11, 0.19])
    y_bot = y_top - jag
    x_bot = -0.66 - 0.03 * np.cos(z / 0.36 * 1.5)
    verts = []
    for zt, yt, xt, yb, xb in zip(z, y_top, x_top, y_bot, x_bot):
        verts.append([xt, yt, zt])
        verts.append([xb, yb, zt])
    verts = np.array(verts)
    faces = []
    for i in range(len(z) - 1):
        a, b, c_, d = 2 * i, 2 * i + 1, 2 * i + 2, 2 * i + 3
        faces.append([a, c_, b])
        faces.append([b, c_, d])
    bang = trimesh.Trimesh(vertices=verts, faces=np.array(faces), process=True)
    return paint(bang)


def build_ahoge():
    """Cowlick loop on top."""
    # small curved tube: torus arc
    tor = trimesh.creation.torus(major_radius=0.09, minor_radius=0.022,
                                 major_sections=10, minor_sections=6)
    v = tor.vertices.copy()
    # keep ~3/4 arc, tilt it
    ang = np.arctan2(v[:, 1], v[:, 0])
    keep = (ang > -2.4) & (ang < 2.4)
    tor = tor.submesh([np.where(keep[tor.faces].all(axis=1))[0]], append=True)
    tor.apply_translation(HC + np.array([0.10, HR[1] * 1.28, 0.02]))
    tor.apply_transform(trimesh.transformations.rotation_matrix(0.5, [0, 0, 1]))
    return paint(tor)


def build_sidelock(side=+1):
    """Chunky tapered lock framing the face."""
    top_c = np.array([HC[0] - 0.40, HC[1] + 0.02, side * 0.33])
    bot_c = np.array([HC[0] - 0.46, HC[1] - 0.30, side * 0.30])
    wt, wb = 0.10, 0.06
    # 8 verts: top square + bottom square
    sq = np.array([[1, 1], [1, -1], [-1, -1], [-1, 1]], float)
    vt = np.column_stack([np.full(4, top_c[0]) + sq[:, 0] * wt * 0.6,
                          np.full(4, top_c[1]),
                          top_c[2] + sq[:, 1] * wt])
    vb = np.column_stack([np.full(4, bot_c[0]) + sq[:, 0] * wb * 0.6,
                          np.full(4, bot_c[1]),
                          bot_c[2] + sq[:, 1] * wb])
    verts = np.vstack([vt, vb])
    faces = [[0, 1, 2], [0, 2, 3],          # top cap
             [4, 6, 5], [4, 7, 6],          # bottom cap
             [0, 4, 5], [0, 5, 1],
             [1, 5, 6], [1, 6, 2],
             [2, 6, 7], [2, 7, 3],
             [3, 7, 4], [3, 4, 0]]
    lock = trimesh.Trimesh(vertices=verts, faces=np.array(faces), process=True)
    return paint(lock)


def main():
    parts = [build_cap(), build_bangs(), build_ahoge(),
             build_sidelock(+1), build_sidelock(-1)]
    hair = trimesh.util.concatenate(parts)
    # keep it low-poly: decimate only if absurdly dense
    if len(hair.faces) > 6000:
        hair = hair.simplify_quadric_decimation(1 - 6000 / len(hair.faces))
        hair = paint(hair)  # decimation resets colors
    hair.export('/tmp/plushy_ref/female_hair.glb')
    print(f'hair built: {len(hair.vertices)} verts, {len(hair.faces)} faces')
    # also a fitted composite preview is rendered separately
    return hair


if __name__ == '__main__':
    main()
