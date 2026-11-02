"""Curvature-integrated per-component sizing HINT (never a face-count
budget/target — see TECH_NOTES.md "Primary objective"). Runs under system
python3 (needs curvature.py / igl / trimesh).

h(v) = clip(sqrt(epsilon / max(kappa(v), floor)), h_min, h_max)   -- user-
confirmed formula. epsilon/h_min/h_max are fractions of the WHOLE ASSET's
bbox diagonal (not the component's own), so components of one asset share
consistent length units — a thin leg and a large flat panel are compared
on the same scale, not each renormalized to look identical.
"""

import json
import os
import sys

import numpy as np

import curvature as curvature_mod


def estimate_component_sizing(component_path, global_diag,
                               epsilon_frac=0.0008, h_min_frac=0.0015,
                               h_max_frac=0.05, floor_kappa=1e-6):
    """Load one component OBJ, compute its own curvature field, derive a
    per-vertex target edge length and an integrated target_faces HINT.
    """
    mesh = curvature_mod.load_mesh(component_path)
    curv = curvature_mod.compute_vertex_curvature(mesh)
    kappa = curv["kappa"]

    epsilon = epsilon_frac * global_diag
    h_min = h_min_frac * global_diag
    h_max = h_max_frac * global_diag

    h = np.sqrt(epsilon / np.maximum(kappa, floor_kappa))
    h = np.clip(h, h_min, h_max)

    area = float(mesh.area)
    mean_h = float(np.mean(h))

    # REAL BUG, found via a raw-asset generality test (854k-tri wooden rack,
    # single unsegmented component): `area / mean(h)^2` collapsed the whole
    # component to ~130 faces, losing every leg/slat/shelf. Root cause: a
    # single component-wide MEAN of h is dominated by whichever region has
    # the most VERTICES, which on a roughly-uniform dense scan is the large
    # flat panels — so a small, high-curvature, high-vertex-density region
    # (a thin leg) barely moves the mean at all, even though it's exactly
    # the region that needs a small h. The correct estimate is the AREA-
    # WEIGHTED INTEGRAL of 1/h(x)^2 over the surface — sum_i(local_area_i /
    # h_i^2) — which gives each region face budget in proportion to its OWN
    # area and OWN curvature, not diluted by how many vertices sit
    # elsewhere. A thin leg with tiny total area but small h now
    # contributes its own proportionally large face count instead of being
    # swamped by the flat panels' vertex count.
    face_areas = mesh.area_faces
    vertex_area = np.zeros(len(mesh.vertices))
    np.add.at(vertex_area, mesh.faces.ravel(), np.repeat(face_areas / 3.0, 3))
    target_faces_hint = max(4, int(round(np.sum(vertex_area / np.maximum(h, 1e-12) ** 2))))

    return {
        "component_path": component_path,
        "n_verts": len(mesh.vertices),
        "area": area,
        "kappa_median": float(np.median(kappa)),
        "kappa_max": float(kappa.max()),
        "mean_h": mean_h,
        "h_min": h_min,
        "h_max": h_max,
        "target_faces_hint": target_faces_hint,
    }


def estimate_manifest_sizing(manifest_path, **kwargs):
    with open(manifest_path) as fh:
        manifest = json.load(fh)

    global_diag = max(c["bbox_diagonal"] for c in manifest["components"])

    results = []
    for c in manifest["components"]:
        try:
            r = estimate_component_sizing(c["path"], global_diag, **kwargs)
        except Exception as e:
            # A degenerate component (e.g. a single dangling edge/point left
            # over from decomposition) shouldn't abort the whole asset —
            # fall back to a minimal hint and flag it for review.
            r = {"component_path": c["path"], "error": str(e), "target_faces_hint": 4}
        r["index"] = c["index"]
        results.append(r)
    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 sizing.py <manifest.json>")
        sys.exit(1)

    results = estimate_manifest_sizing(sys.argv[1])
    print("SIZING_RESULT_JSON_START")
    print(json.dumps(results, indent=2))
    print("SIZING_RESULT_JSON_END")
