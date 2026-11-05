"""Continuous curvature-weighted edge protection/cost field — pure Python
(numpy/EditMesh, no Blender), operating on ONE component's remeshed mesh
at a time.

Fixes two concrete tripo_smart_engine (`ribbon_engine.py`) bugs:
1. The micro-feature rule used the GLOBAL median face area of the whole
   joined mesh as its baseline, blanket-protecting an entire small region
   (e.g. the jade sword's hilt) even where that region is locally flat.
   Here the baseline is always this component's OWN median face area —
   already correct by construction, since components stay separate
   (see decompose.py) all the way through this stage.
2. Protection was binary (two fixed angle tiers). Here every non-hard-
   protected edge gets a CONTINUOUS dissolve cost so dissolve.py can prefer
   the flattest/least-detailed edges first instead of stepping between
   3deg/18deg tiers — density tapers smoothly from a feature outward.

Hard-protected (cost = math.inf, i.e. the Primary-objective feature gate
that nothing may violate): boundary edges, true creases (dihedral >=
CREASE_DEG), and edges touching a dome/saddle (pole-like) vertex.
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import config
import io_mesh


def compute_edge_costs(mesh, crease_deg=config.CREASE_DEG,
                        micro_curve_deg=config.MICRO_FEATURE_CURVE_DEG,
                        micro_area_frac=config.MICRO_FEATURE_AREA_FRAC,
                        dome_saddle_deg=config.DOME_SADDLE_DEG,
                        local_median_area=None):
    """Return {edge_id: cost} for every edge in mesh. cost == math.inf means
    hard-protected (never dissolve); lower finite cost = safer/cheaper to
    dissolve first.

    local_median_area: pass a precomputed value (e.g. from the mesh's state
    before a multi-pass dissolve loop started) to skip the O(faces) median
    recompute on every call — dissolve.py's loop calls this every pass, and
    the component's own characteristic scale doesn't need to track the
    shrinking face count that precisely pass to pass. Leave None to compute
    it fresh from the mesh's current faces (the previous, always-live
    behavior).
    """
    crease_rad = math.radians(crease_deg)
    micro_curve_rad = math.radians(micro_curve_deg)
    dome_saddle_rad = math.radians(dome_saddle_deg)

    # recalc_face_normals() here is a plain per-face Newell computation —
    # NOT a winding fix (see its own docstring). Callers that loop many
    # times over a mesh whose winding is already known-consistent (e.g.
    # dissolve.py's pass loop, which fixes winding once up front and keeps
    # it consistent via merge_faces) should rely on that, rather than this
    # repeated call somehow re-correcting bad winding — it no longer does.
    mesh.recalc_face_normals()

    if local_median_area is None:
        face_areas = np.array([mesh.calc_area(f) for f in mesh.faces]) if list(mesh.faces) else np.array([0.0])
        local_median_area = float(np.median(face_areas)) if len(face_areas) else 0.0

    hard_protected = set()
    costs = {}

    # Dome/saddle hard-protect: vertices whose surrounding face normals
    # deviate a lot on average (poles/singularities) lock all their edges.
    dome_saddle_verts = set()
    for v in mesh.verts:
        link_faces = set()
        for e in mesh.link_edges(v):
            link_faces.update(mesh.link_faces(e))
        if len(link_faces) < 4:
            continue
        norms = [mesh.face_normal(f) for f in link_faces if np.linalg.norm(mesh.face_normal(f)) > 1e-4]
        if len(norms) < 3:
            continue
        avg_n = np.sum(norms, axis=0)
        avg_len = np.linalg.norm(avg_n)
        if avg_len < 1e-6:
            # Surrounding normals nearly cancel out (a real but rare case at
            # a sharp fold) — no well-defined "average deviation" here.
            # Treat the vertex conservatively as a hard feature.
            dome_saddle_verts.add(v)
            continue
        avg_n = avg_n / avg_len
        devs = [_angle_between(n, avg_n) for n in norms]
        if devs and (sum(devs) / len(devs)) > dome_saddle_rad:
            dome_saddle_verts.add(v)

    for e in mesh.edges:
        if mesh.is_boundary(e):
            hard_protected.add(e)
            costs[e] = math.inf
            continue

        link_faces = mesh.link_faces(e)
        if len(link_faces) != 2:
            # Non-manifold — never a safe dissolve candidate.
            hard_protected.add(e)
            costs[e] = math.inf
            continue

        f0, f1 = link_faces
        n0, n1 = mesh.face_normal(f0), mesh.face_normal(f1)
        if np.linalg.norm(n0) < 1e-4 or np.linalg.norm(n1) < 1e-4:
            costs[e] = 0.0
            continue
        ang = _angle_between(n0, n1)

        if ang >= crease_rad:
            hard_protected.add(e)
            costs[e] = math.inf
            continue

        v0, v1 = mesh.edge_verts(e)
        if (v0 in dome_saddle_verts or v1 in dome_saddle_verts) and ang > micro_curve_rad:
            # Only lock dome/saddle neighborhood edges that actually curve;
            # flat transverse edges (ang <= micro_curve_rad) meeting a straight
            # 90-deg crease are safe ribbon-simplification candidates.
            hard_protected.add(e)
            costs[e] = math.inf
            continue

        cost = ang  # base: flatter pairs (smaller dihedral) are cheaper

        # Continuous micro-feature bonus (replaces the old binary rule):
        # only kicks in once there's real curvature (ang > micro_curve_rad)
        # AND the smaller adjacent face is small relative to THIS
        # component's own median — scales smoothly with how small/curved
        # it is, instead of an all-or-nothing protect.
        if ang > micro_curve_rad and local_median_area > 0:
            f_min_area = min(mesh.calc_area(f0), mesh.calc_area(f1))
            threshold = local_median_area * micro_area_frac
            if f_min_area < threshold:
                shrink_frac = 1.0 - (f_min_area / threshold)
                cost += shrink_frac * crease_rad  # up to ~crease cost, never inf

        costs[e] = cost

    return costs, hard_protected, local_median_area


def _angle_between(a, b):
    """Angle in radians between two (assumed near-unit) vectors — matches
    mathutils.Vector.angle()."""
    cos_a = float(np.clip(np.dot(a, b), -1.0, 1.0))
    return math.acos(cos_a)


def compute_costs_for_obj(obj_path, **kwargs):
    mesh = io_mesh.load(obj_path)
    if not list(mesh.faces):
        return {"error": "no mesh faces found"}
    costs, hard_protected, local_median_area = compute_edge_costs(mesh, **kwargs)

    finite = [c for c in costs.values() if math.isfinite(c)]
    summary = {
        "obj_path": obj_path,
        "n_edges": len(costs),
        "n_hard_protected": len(hard_protected),
        "hard_protected_frac": round(len(hard_protected) / max(1, len(costs)), 4),
        "local_median_face_area": local_median_area,
        "finite_cost_min": min(finite) if finite else None,
        "finite_cost_median": float(np.median(finite)) if finite else None,
        "finite_cost_max": max(finite) if finite else None,
    }
    return summary


def dump_edges_for_render(obj_path, out_json, **kwargs):
    """Export every edge's endpoint coordinates + cost/protected flag, so a
    separate script can render a color-coded wireframe for an eye check —
    required verification, not optional, per the "no step moves forward
    unverified" instruction."""
    mesh = io_mesh.load(obj_path)
    costs, hard_protected, local_median_area = compute_edge_costs(mesh, **kwargs)

    edges_out = []
    for e in mesh.edges:
        v0, v1 = mesh.edge_verts(e)
        p0, p1 = mesh.vert_co(v0), mesh.vert_co(v1)
        edges_out.append({
            "p0": [float(p0[0]), float(p0[1]), float(p0[2])],
            "p1": [float(p1[0]), float(p1[1]), float(p1[2])],
            "cost": None if math.isinf(costs[e]) else costs[e],
            "protected": e in hard_protected,
        })
    with open(out_json, "w") as fh:
        json.dump({"obj_path": obj_path, "edges": edges_out}, fh)
    return out_json


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Usage: python3 protect.py <component.obj> [--dump-edges out.json]")
        sys.exit(1)

    if "--dump-edges" in args:
        idx = args.index("--dump-edges")
        dump_edges_for_render(args[0], args[idx + 1])
        print(f"Dumped edges to {args[idx + 1]}")
    else:
        summary = compute_costs_for_obj(args[0])
        print("PROTECT_SUMMARY_JSON_START")
        print(json.dumps(summary, indent=2))
        print("PROTECT_SUMMARY_JSON_END")
