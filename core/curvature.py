"""Per-vertex curvature field on the dense input mesh.

Runs under plain system python3 (needs trimesh + libigl). Accepts any
format trimesh can load directly (.obj, .glb/.gltf, .ply, .stl). FBX is
not supported by this pipeline's pure-Python backend (trimesh cannot
reliably parse FBX, and there is no Blender dependency left to fall back
on) — pre-convert .fbx assets to .obj/.glb first.

This is the one piece none of the three prior efforts (tripo_smart_engine,
tripo-logic-approach(-v2), burger_stand_retopo.py) has: a real, continuous,
stored curvature field used downstream for both sizing (sizing.py) and
protection (protect.py), replacing ad hoc transient dihedral-angle checks.
"""

import json
import os
import sys

import numpy as np
import trimesh
import trimesh.curvature as tc

try:
    import igl
    HAS_IGL = True
except ImportError:
    HAS_IGL = False


def load_mesh(path):
    mesh = trimesh.load(path, process=False, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError(f"{path} did not load as a single Trimesh (got {type(mesh)})")
    return mesh


def compute_vertex_curvature(mesh: trimesh.Trimesh, radius=5):
    """Return per-vertex curvature arrays via libigl's principal curvature.

    radius: libigl's `principal_curvature` neighborhood radius in rings —
    a topology-relative parameter (number of edge-hops), already
    scale-independent, not an absolute distance.
    """
    v = np.asarray(mesh.vertices, dtype=np.float64)
    f = np.asarray(mesh.faces, dtype=np.int64)

    if HAS_IGL:
        pd1, pd2, pv1, pv2, bad_vertices = igl.principal_curvature(v, f, radius=radius)
        if bad_vertices:
            pass
        kappa = np.maximum(np.abs(pv1), np.abs(pv2))
        mean_curvature = 0.5 * (pv1 + pv2)
        gaussian_curvature = pv1 * pv2
    else:
        defects = np.abs(tc.vertex_defects(mesh))
        kappa = defects
        pv1 = kappa
        pv2 = kappa
        pd1 = np.zeros_like(v)
        pd2 = np.zeros_like(v)
        mean_curvature = kappa
        gaussian_curvature = kappa ** 2

    return {
        "k1": pv1,
        "k2": pv2,
        "kappa": kappa,
        "mean_curvature": mean_curvature,
        "gaussian_curvature": gaussian_curvature,
        "pd1": pd1,
        "pd2": pd2,
    }


def save_curvature(path_npz, curvature_dict):
    os.makedirs(os.path.dirname(os.path.abspath(path_npz)) or ".", exist_ok=True)
    np.savez(path_npz, **curvature_dict)


def load_curvature(path_npz):
    data = np.load(path_npz)
    return {k: data[k] for k in data.files}


def render_curvature_preview(mesh: trimesh.Trimesh, kappa: np.ndarray, out_png: str,
                              title: str = ""):
    """Quick color-by-curvature render for an eye-check (T2's verification
    step) — not a production visualization, just a correctness sanity check."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    v = mesh.vertices
    f = mesh.faces

    # Clip to a percentile range so a few outlier vertices don't wash out
    # the color scale (curvature distributions are heavily right-skewed).
    lo, hi = np.percentile(kappa, [2, 98])
    hi = max(hi, lo + 1e-9)
    norm_k = np.clip((kappa - lo) / (hi - lo), 0, 1)
    face_k = norm_k[f].mean(axis=1)

    cmap = plt.get_cmap("inferno")
    face_colors = cmap(face_k)

    fig = plt.figure(figsize=(8, 8))
    ax = fig.add_subplot(111, projection="3d")
    poly = Poly3DCollection(v[f], facecolors=face_colors, edgecolor="none")
    ax.add_collection3d(poly)

    mins, maxs = v.min(axis=0), v.max(axis=0)
    center = (mins + maxs) / 2
    span = (maxs - mins).max() / 2 * 1.1
    ax.set_xlim(center[0] - span, center[0] + span)
    ax.set_ylim(center[1] - span, center[1] + span)
    ax.set_zlim(center[2] - span, center[2] + span)
    ax.set_box_aspect([1, 1, 1])
    ax.set_axis_off()
    ax.set_title(title or "Curvature (dark=low, bright=high)")

    os.makedirs(os.path.dirname(os.path.abspath(out_png)) or ".", exist_ok=True)
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 curvature.py <mesh_file> [out_prefix]")
        sys.exit(1)

    mesh_path = sys.argv[1]
    out_prefix = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(mesh_path)[0]

    mesh = load_mesh(mesh_path)
    curv = compute_vertex_curvature(mesh)

    save_curvature(out_prefix + "_curvature.npz", curv)
    render_curvature_preview(mesh, curv["kappa"], out_prefix + "_curvature.png",
                              title=os.path.basename(mesh_path))

    summary = {
        "n_verts": len(mesh.vertices),
        "kappa_min": float(curv["kappa"].min()),
        "kappa_max": float(curv["kappa"].max()),
        "kappa_median": float(np.median(curv["kappa"])),
        "kappa_p90": float(np.percentile(curv["kappa"], 90)),
    }
    print("CURVATURE_SUMMARY_JSON_START")
    print(json.dumps(summary, indent=2))
    print("CURVATURE_SUMMARY_JSON_END")
