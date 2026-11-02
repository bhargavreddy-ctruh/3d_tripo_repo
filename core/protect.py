"""Continuous curvature-weighted edge protection/cost field — runs under
Blender (bpy/bmesh), operating on ONE component's remeshed mesh at a time.

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

import bpy
import bmesh
import numpy as np

import config
import io_blender


def compute_edge_costs(bm, crease_deg=config.CREASE_DEG,
                        micro_curve_deg=config.MICRO_FEATURE_CURVE_DEG,
                        micro_area_frac=config.MICRO_FEATURE_AREA_FRAC,
                        dome_saddle_deg=config.DOME_SADDLE_DEG):
    """Return {edge_index: cost} for every edge in bm. cost == math.inf means
    hard-protected (never dissolve); lower finite cost = safer/cheaper to
    dissolve first.
    """
    crease_rad = math.radians(crease_deg)
    micro_curve_rad = math.radians(micro_curve_deg)
    dome_saddle_rad = math.radians(dome_saddle_deg)

    # Remeshers (Instant Meshes especially) don't always emit consistent
    # face winding, which makes every normal-angle-based test below (crease,
    # dome/saddle, micro-feature) see false huge deviations on an otherwise
    # flat region. Must recalc before any angle test.
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()

    # LOCAL median face area — this component's own faces only. This is the
    # direct fix for the global-median bug: a small, genuinely-flat region
    # of a small component is judged against ITS OWN scale, not the whole
    # (possibly much larger) joined asset.
    face_areas = np.array([f.calc_area() for f in bm.faces]) if bm.faces else np.array([0.0])
    local_median_area = float(np.median(face_areas)) if len(face_areas) else 0.0

    hard_protected = set()
    costs = {}

    # Dome/saddle hard-protect: vertices whose surrounding face normals
    # deviate a lot on average (poles/singularities) lock all their edges.
    dome_saddle_verts = set()
    for v in bm.verts:
        if len(v.link_faces) < 4:
            continue
        norms = [f.normal for f in v.link_faces if f.normal.length > 1e-4]
        if len(norms) < 3:
            continue
        avg_n = sum(norms, norms[0].__class__((0, 0, 0)))
        if avg_n.length < 1e-6:
            # Surrounding normals nearly cancel out (a real but rare case at
            # a sharp fold) — Vector.angle() raises on a zero-length vector,
            # so there's no well-defined "average deviation" here. Treat the
            # vertex conservatively as a hard feature instead of crashing.
            dome_saddle_verts.add(v.index)
            continue
        avg_n.normalize()
        devs = [f.normal.angle(avg_n) for f in v.link_faces if f.normal.length > 1e-4]
        if devs and (sum(devs) / len(devs)) > dome_saddle_rad:
            dome_saddle_verts.add(v.index)

    for e in bm.edges:
        if e.is_boundary:
            hard_protected.add(e.index)
            costs[e.index] = math.inf
            continue
        if e.verts[0].index in dome_saddle_verts or e.verts[1].index in dome_saddle_verts:
            hard_protected.add(e.index)
            costs[e.index] = math.inf
            continue
        if len(e.link_faces) != 2:
            # Non-manifold — never a safe dissolve candidate.
            hard_protected.add(e.index)
            costs[e.index] = math.inf
            continue

        f0, f1 = e.link_faces
        n0, n1 = f0.normal, f1.normal
        if n0.length < 1e-4 or n1.length < 1e-4:
            costs[e.index] = 0.0
            continue
        ang = n0.angle(n1)

        if ang >= crease_rad:
            hard_protected.add(e.index)
            costs[e.index] = math.inf
            continue

        cost = ang  # base: flatter pairs (smaller dihedral) are cheaper

        # Continuous micro-feature bonus (replaces the old binary rule):
        # only kicks in once there's real curvature (ang > micro_curve_rad)
        # AND the smaller adjacent face is small relative to THIS
        # component's own median — scales smoothly with how small/curved
        # it is, instead of an all-or-nothing protect.
        if ang > micro_curve_rad and local_median_area > 0:
            f_min_area = min(f0.calc_area(), f1.calc_area())
            threshold = local_median_area * micro_area_frac
            if f_min_area < threshold:
                shrink_frac = 1.0 - (f_min_area / threshold)
                cost += shrink_frac * crease_rad  # up to ~crease cost, never inf

        costs[e.index] = cost

    return costs, hard_protected, local_median_area


def compute_costs_for_obj(obj_path, **kwargs):
    io_blender.clear_scene()
    mesh_objs = io_blender.import_mesh(obj_path)
    if not mesh_objs:
        return {"error": "no mesh objects found"}
    obj = mesh_objs[0]
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    costs, hard_protected, local_median_area = compute_edge_costs(bm, **kwargs)

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
    bm.free()
    return summary


def dump_edges_for_render(obj_path, out_json, **kwargs):
    """Export every edge's endpoint coordinates + cost/protected flag, so a
    separate (non-bpy) script can render a color-coded wireframe for an eye
    check — required verification, not optional, per the "no step moves
    forward unverified" instruction."""
    io_blender.clear_scene()
    mesh_objs = io_blender.import_mesh(obj_path)
    obj = mesh_objs[0]
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    costs, hard_protected, local_median_area = compute_edge_costs(bm, **kwargs)

    bm.edges.ensure_lookup_table()
    edges_out = []
    for e in bm.edges:
        v0, v1 = e.verts[0].co, e.verts[1].co
        edges_out.append({
            "p0": [v0.x, v0.y, v0.z],
            "p1": [v1.x, v1.y, v1.z],
            "cost": None if math.isinf(costs[e.index]) else costs[e.index],
            "protected": e.index in hard_protected,
        })
    with open(out_json, "w") as fh:
        json.dump({"obj_path": obj_path, "edges": edges_out}, fh)
    bm.free()
    return out_json


if __name__ == "__main__":
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    if not args:
        print("Usage: blender --background --python protect.py -- <component.obj> [--dump-edges out.json]")
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
