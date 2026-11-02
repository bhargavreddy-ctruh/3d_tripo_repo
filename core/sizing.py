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


def apply_face_budget(results, total_input_faces, min_budget_frac=None, max_budget_frac=None,
                       min_faces_per_component=4):
    """Scale every component's curvature-derived target_faces_hint
    proportionally so the SUM across the whole asset lands inside
    `[min_budget_frac, max_budget_frac] * total_input_faces`, without
    changing the RELATIVE curvature-driven distribution between components
    (a thin high-curvature part still gets proportionally more of the
    budget than a large flat one — this only rescales the overall total,
    it doesn't re-derive the shape of the estimate).

    This is a BAND, not a fixed target: if curvature's own raw estimate
    already falls inside the band, nothing is touched at all (trust the
    curvature-driven estimate). Only scaled DOWN if the raw estimate
    exceeds `max_budget_frac` (too dense/heavy for this constraint), and
    only scaled UP if it falls short of `min_budget_frac` (so a part with
    almost no curvature isn't starved below a usable minimum — this is
    what "preserve every feature and smoothness" calls for: a floor
    protects feature/smoothness-bearing faces from being scaled away to
    nothing, a ceiling just prevents runaway density). Either bound may be
    `None` to leave that side open.

    Opt-in only (see `estimate_manifest_sizing`'s defaults of `None`) — per
    this project's Primary objective, there is normally no fixed
    face-count budget; this exists because the user explicitly asked for
    one.
    """
    raw_total = sum(r.get("target_faces_hint_raw", r["target_faces_hint"])
                     for r in results if "error" not in r)
    lo = max(1, int(round(min_budget_frac * total_input_faces))) if min_budget_frac is not None else None
    hi = max(1, int(round(max_budget_frac * total_input_faces))) if max_budget_frac is not None else None

    if hi is not None and raw_total > hi:
        scale = hi / max(1, raw_total)
        budget_total = hi
    elif lo is not None and raw_total < lo:
        scale = lo / max(1, raw_total)
        budget_total = lo
    else:
        scale = 1.0
        budget_total = raw_total

    for r in results:
        if "error" in r:
            continue
        raw = r.get("target_faces_hint_raw", r["target_faces_hint"])
        r["target_faces_hint_raw"] = raw
        r["target_faces_hint"] = max(min_faces_per_component, int(round(raw * scale)))

    return {
        "total_input_faces": total_input_faces,
        "min_budget_frac": min_budget_frac,
        "max_budget_frac": max_budget_frac,
        "min_budget_faces": lo,
        "max_budget_faces": hi,
        "raw_total_faces_hint": raw_total,
        "scale_applied": scale,
        "target_total_faces": budget_total,
    }


def estimate_manifest_sizing(manifest_path, min_budget_frac=None, max_budget_frac=None, **kwargs):
    """`min_budget_frac`/`max_budget_frac`: if either is given (e.g.
    min=0.01, max=0.05 for a 1%-5%-of-input-faces band), scales all
    per-component hints (proportionally, preserving the curvature-driven
    distribution) so their sum lands inside that band — up if curvature's
    own estimate would fall short of the floor, down if it would exceed
    the ceiling, untouched if already inside the band. Both `None`
    (default) keeps this project's normal behavior: no fixed budget, each
    component's hint is purely its own curvature-integrated estimate.
    """
    with open(manifest_path) as fh:
        manifest = json.load(fh)

    global_diag = max(c["bbox_diagonal"] for c in manifest["components"])
    total_input_faces = sum(c["faces"] for c in manifest["components"])

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

    budget_stats = None
    if min_budget_frac is not None or max_budget_frac is not None:
        budget_stats = apply_face_budget(results, total_input_faces, min_budget_frac, max_budget_frac)

    return results, budget_stats


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 sizing.py <manifest.json> [min_budget_frac] [max_budget_frac]")
        sys.exit(1)

    min_budget_frac = float(sys.argv[2]) if len(sys.argv) > 2 else None
    max_budget_frac = float(sys.argv[3]) if len(sys.argv) > 3 else None
    results, budget_stats = estimate_manifest_sizing(
        sys.argv[1], min_budget_frac=min_budget_frac, max_budget_frac=max_budget_frac)
    print("SIZING_RESULT_JSON_START")
    print(json.dumps({"results": results, "budget": budget_stats}, indent=2))
    print("SIZING_RESULT_JSON_END")
