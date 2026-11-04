"""Coplanar triangle-pair / diamond-dart merging — ports
tripo_smart_engine's `apply_diamond_dart_adapters` (ribbon_engine.py).
Blender's own `bmesh.ops.join_triangles` has no library equivalent, so this
is a direct hand-written reimplementation of the same geometric test: merge
two adjacent triangles into a quad when they're coplanar enough and their
combined shape isn't too skewed. Pure Python (EditMesh.merge_faces), no
Blender.
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import config
import io_mesh


def _quad_corner_angles(mesh, quad_verts):
    """Interior angle (radians) at each of the 4 corners of a planar-ish
    quad, used as the "shape squareness" test — a perfect square/rectangle
    has all 4 angles at 90deg; a sliver/bowtie quad deviates sharply."""
    coords = [mesh.vert_co(v) for v in quad_verts]
    angles = []
    n = len(coords)
    for i in range(n):
        prev_v = coords[(i - 1) % n]
        cur_v = coords[i]
        next_v = coords[(i + 1) % n]
        a = prev_v - cur_v
        b = next_v - cur_v
        la, lb = np.linalg.norm(a), np.linalg.norm(b)
        if la < 1e-12 or lb < 1e-12:
            angles.append(math.pi)  # degenerate corner — treat as worst-case
            continue
        cos_a = float(np.clip(np.dot(a, b) / (la * lb), -1.0, 1.0))
        angles.append(math.acos(cos_a))
    return angles


def merge_coplanar_triangle_pairs(mesh, angle_face_deg=config.COPLANAR_DART_DEG,
                                   angle_shape_deg=90.0):
    mesh.recalc_face_normals()
    angle_face_rad = math.radians(angle_face_deg)
    # Max allowed deviation of each quad corner angle from 90deg.
    # angle_shape_deg=90 (the default used everywhere this is called) means
    # "barely restrict shape at all, rely mainly on the face-angle
    # threshold" — a corner angle can range anywhere in (0, 180) and still
    # pass, matching Blender join_triangles' own very lenient default.
    shape_tol_rad = math.radians(angle_shape_deg)

    tris = {f for f in mesh.faces if len(mesh.face_verts(f)) == 3}
    n_tris_before = len(tris)

    # Candidate (edge, score) pairs: every interior edge shared by exactly
    # two triangles, both thresholds passed, scored flattest+squarest-first
    # (same greedy, cheapest-first style the rest of this codebase uses).
    candidates = []
    seen_edges = set()
    for t in tris:
        for e in mesh.face_edges(t):
            if e in seen_edges:
                continue
            seen_edges.add(e)
            link = mesh.link_faces(e)
            if len(link) != 2:
                continue
            f0, f1 = link
            if f0 not in tris or f1 not in tris:
                continue
            n0, n1 = mesh.face_normal(f0), mesh.face_normal(f1)
            if np.linalg.norm(n0) < 1e-9 or np.linalg.norm(n1) < 1e-9:
                continue
            face_angle = math.acos(float(np.clip(np.dot(n0, n1), -1.0, 1.0)))
            if face_angle >= angle_face_rad:
                continue

            v0, v1 = mesh.edge_verts(e)
            verts0 = mesh.face_verts(f0)
            verts1 = mesh.face_verts(f1)
            opp0 = next(v for v in verts0 if v not in (v0, v1))
            opp1 = next(v for v in verts1 if v not in (v0, v1))
            # Build the quad in boundary order: v0, opp0, v1, opp1 (or the
            # reverse) — whichever matches f0's own winding at v0->v1, so the
            # merged face's winding stays consistent with its neighbors.
            quad = (v0, opp1, v1, opp0) if _edge_forward(mesh, f0, v0, v1) else (v1, opp1, v0, opp0)
            max_dev = max(abs(a - math.pi / 2) for a in _quad_corner_angles(mesh, quad))
            if max_dev > shape_tol_rad:
                continue

            score = face_angle + max_dev  # flatter + squarer sorts first
            candidates.append((score, e, f0, f1))

    candidates.sort(key=lambda c: c[0])
    claimed = set()
    pairs_merged = 0
    for _score, e, f0, f1 in candidates:
        if f0 in claimed or f1 in claimed:
            continue
        if f0 not in mesh._face_verts or f1 not in mesh._face_verts:
            continue
        new_fid = mesh.merge_faces({f0, f1}, dissolve_verts=False)
        if new_fid is not None:
            claimed.add(f0)
            claimed.add(f1)
            pairs_merged += 1

    mesh.faces  # no-op, kept for symmetry with original's ensure_lookup_table
    n_tris_after = sum(1 for f in mesh.faces if len(mesh.face_verts(f)) == 3)
    return {"tris_before": n_tris_before, "tris_after": n_tris_after,
            "pairs_merged": pairs_merged}


def _edge_forward(mesh, face, v0, v1):
    """True if face's own vertex loop visits v0 immediately before v1
    (i.e. the edge runs v0->v1 in this face's winding direction)."""
    verts = mesh.face_verts(face)
    n = len(verts)
    idx = verts.index(v0)
    return verts[(idx + 1) % n] == v1


def merge_obj_file(in_obj, out_obj, **kwargs):
    mesh = io_mesh.load(in_obj)

    n_boundary_before = len(mesh.boundary_edges())
    stats = merge_coplanar_triangle_pairs(mesh, **kwargs)
    n_boundary_after = len(mesh.boundary_edges())
    if n_boundary_after > n_boundary_before:
        raise RuntimeError(
            f"darts: boundary edges grew {n_boundary_before} -> {n_boundary_after}"
        )
    stats["boundary_before"] = n_boundary_before
    stats["boundary_after"] = n_boundary_after

    io_mesh.export(out_obj, mesh, quads=True)
    stats["out_obj"] = out_obj
    return stats


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 2:
        print("Usage: python3 darts.py <in.obj> <out.obj>")
        sys.exit(1)
    stats = merge_obj_file(args[0], args[1])
    print("DARTS_RESULT_JSON_START")
    print(json.dumps(stats, indent=2))
    print("DARTS_RESULT_JSON_END")
