"""Honest (non-triangulated) wireframe renderer for vacuum_quad_engine QA.

Per TECH_NOTES.md's "Methodology fix: honest (non-triangulated) rendering":
`trimesh.load(..., force='mesh')` always triangulates every face internally,
so a genuinely clean quad-dominant mesh and a real triangle fan render
IDENTICALLY via Poly3DCollection (both show a diagonal through every face).
This script parses an OBJ file directly, keeping each face's REAL vertex
count (quad, n-gon, triangle) and feeds variable-length polygons straight to
Poly3DCollection -- no forced triangulation anywhere. Use this (not
trimesh.load force='mesh') for every before/after render in this project.

Usage: python3 render_honest_wireframe.py <in.obj> <out.png> [--title "..."] [--elev E] [--azim A] [--color-by-size]
"""
import sys
import argparse
import numpy as np


def load_obj_honest(path):
    """Parse an OBJ file's v/f lines directly. Returns (verts Nx3 array,
    faces: list of int lists, each face's real vertex count preserved)."""
    verts = []
    faces = []
    with open(path) as fh:
        for line in fh:
            if line.startswith("v "):
                parts = line.split()
                verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
            elif line.startswith("f "):
                parts = line.split()[1:]
                idxs = []
                for p in parts:
                    # OBJ face refs can be v, v/vt, v/vt/vn, v//vn
                    vi = p.split("/")[0]
                    idxs.append(int(vi) - 1 if int(vi) > 0 else len(verts) + int(vi))
                faces.append(idxs)
    return np.array(verts, dtype=np.float64), faces


def render(in_obj, out_png, title="", elev=25, azim=-60, color_by_size=True,
           figsize=(9, 9), dpi=150):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    verts, faces = load_obj_honest(in_obj)
    n_quads = sum(1 for f in faces if len(f) == 4)
    n_tris = sum(1 for f in faces if len(f) == 3)
    n_ngons = sum(1 for f in faces if len(f) > 4)

    polys = [verts[f] for f in faces]
    if color_by_size:
        colors = []
        for f in faces:
            if len(f) == 3:
                colors.append((0.85, 0.25, 0.25, 0.9))   # red = triangle
            elif len(f) == 4:
                colors.append((0.55, 0.75, 0.95, 0.9))   # blue = quad
            else:
                colors.append((0.95, 0.75, 0.25, 0.9))   # orange = n-gon
    else:
        colors = (0.75, 0.80, 0.85, 0.9)

    fig = plt.figure(figsize=figsize)
    ax = fig.add_subplot(111, projection="3d")

    mins, maxs = verts.min(axis=0), verts.max(axis=0)
    center = (mins + maxs) / 2
    span = (maxs - mins).max() / 2 * 1.15
    ax.set_xlim(center[0] - span, center[0] + span)
    ax.set_ylim(center[1] - span, center[1] + span)
    ax.set_zlim(center[2] - span, center[2] + span)
    ax.set_box_aspect([1, 1, 1])
    ax.set_axis_off()

    coll = Poly3DCollection(polys, facecolors=colors, edgecolors="black", linewidths=0.4)
    ax.add_collection3d(coll, autolim=False)
    ax.view_init(elev=elev, azim=azim)
    ax.set_title(f"{title}\nfaces={len(faces)} quads={n_quads} tris={n_tris} ngons={n_ngons}")

    fig.savefig(out_png, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return {"faces": len(faces), "quads": n_quads, "tris": n_tris, "ngons": n_ngons,
            "out_png": out_png}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("in_obj")
    ap.add_argument("out_png")
    ap.add_argument("--title", default="")
    ap.add_argument("--elev", type=float, default=25)
    ap.add_argument("--azim", type=float, default=-60)
    args = ap.parse_args()
    info = render(args.in_obj, args.out_png, title=args.title or args.in_obj,
                   elev=args.elev, azim=args.azim)
    print(info)
