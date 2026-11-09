"""Parallel-chord quad caps for near-planar boundary loops — ports the
bevel-ring + parallel-chord-strip construction from
`/Users/bhargavreddy/anisotropic Quad Dominant/burger_stand_retopo.py`,
which eliminates the center-pole triangle-fan pattern a generic remesher
leaves on flat circular/polygonal caps (confirmed 100% quads on its own
disk/dome/cylinder-cap benchmarks). Pure Python (EditMesh), no Blender.

For an even-length boundary loop: an inset "bevel ring" (N quads) borders
the loop, and the remaining interior is tiled by N/2-1 parallel chord
quads connecting mirrored vertex pairs — zero triangles, zero center pole.
Odd-length loops fall back untouched (flagged in the result) rather than
guessing a lossy construction.
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import io_mesh
from editmesh import EditMesh
import dome_caps


def _is_planar(coords, tol_frac=0.02):
    """Fit a plane via the polygon's own average normal (Newell's method) +
    centroid and check max deviation relative to the loop's own bounding
    diagonal."""
    centroid = np.mean(coords, axis=0)
    normal = np.zeros(3)
    n = len(coords)
    for i in range(n):
        a, b = coords[i], coords[(i + 1) % n]
        normal[0] += (a[1] - b[1]) * (a[2] + b[2])
        normal[1] += (a[2] - b[2]) * (a[0] + b[0])
        normal[2] += (a[0] - b[0]) * (a[1] + b[1])
    length = np.linalg.norm(normal)
    if length < 1e-9:
        return False, centroid, normal
    normal = normal / length
    diag = max(np.linalg.norm(c - centroid) for c in coords) * 2 or 1.0
    max_dev = max(abs(np.dot(c - centroid, normal)) for c in coords)
    return (max_dev / diag) < tol_frac, centroid, normal


def cap_boundary_loop(mesh, loop_edges, inset_frac=0.88):
    """loop_edges: an ordered, closed sequence of boundary edge ids.
    Returns a dict with ok/skipped and counts. Fills the hole in place.
    """
    loop_edge_set = set(loop_edges)
    verts = []
    seen_edges = set()
    e0 = loop_edges[0]
    v = mesh.edge_verts(e0)[0]
    for _ in range(len(loop_edges)):
        verts.append(v)
        for e in mesh.link_edges(v):
            if e in loop_edge_set and e not in seen_edges:
                seen_edges.add(e)
                v = mesh.other_vert(e, v)
                break
    if len(verts) != len(loop_edges):
        return {"ok": False, "reason": "could not order loop"}

    n = len(verts)
    if n % 2 != 0:
        return {"ok": False, "reason": f"odd loop length {n}, skipped (no lossy fallback)"}

    coords = [mesh.vert_co(v).copy() for v in verts]
    planar, centroid, normal = _is_planar(coords)
    if not planar:
        # Curved (dome/saddle) boundary loop: route to the curvature-sign-
        # aware quad-dome/socket capper instead of leaving it open. Report
        # its own ok/reason verbatim rather than masking as "not planar
        # enough" — a rejection here (e.g. its own aspect-ratio guard) is a
        # distinct, more specific failure mode.
        return dome_caps.cap_dome_saddle_loop(mesh, loop_edges, verts, coords)

    # Guard: skip long skinny boundary slits to prevent creating 1D barcode slats
    t1 = np.cross(normal, [0, 0, 1]) if abs(normal[2]) < 0.9 else np.cross(normal, [1, 0, 0])
    l1 = np.linalg.norm(t1)
    if l1 > 1e-9:
        t1 = t1 / l1
        t2 = np.cross(normal, t1)
        u = [np.dot(c - centroid, t1) for c in coords]
        v_coords = [np.dot(c - centroid, t2) for c in coords]
        span_u = max(u) - min(u)
        span_v = max(v_coords) - min(v_coords)
        loop_ar = max(span_u, span_v) / max(min(span_u, span_v), 1e-6)
        if loop_ar > 3.0:
            return {"ok": False, "reason": f"loop aspect ratio {loop_ar:.2f} > 3.0, skipped"}

    if n == 4:
        mesh.add_face(verts)
        return {"ok": True, "loop_len": 4, "bevel_quads": 1, "chord_quads": 0}
    elif n == 6:
        mesh.add_face([verts[0], verts[1], verts[2], verts[5]])
        mesh.add_face([verts[5], verts[2], verts[3], verts[4]])
        return {"ok": True, "loop_len": 6, "bevel_quads": 2, "chord_quads": 0}

    # For n >= 8: balanced inset (0.5), not extreme (0.88)
    inset_frac = 0.5
    inset_verts = [mesh.add_vert(centroid + (c - centroid) * inset_frac) for c in coords]
    new_faces = []
    for i in range(n):
        j = (i + 1) % n
        new_faces.append([verts[i], verts[j], inset_verts[j], inset_verts[i]])

    half = n // 2
    chord_pairs = [(inset_verts[i], inset_verts[i + half]) for i in range(half)]
    for i in range(half - 1):
        a0, a1 = chord_pairs[i]
        b0, b1 = chord_pairs[i + 1]
        new_faces.append([a0, b0, b1, a1])

    # Check aspect ratio of all proposed cap quads to prevent barcode slats
    for f in new_faces:
        v0, v1, v2, v3 = (mesh.vert_co(v) for v in f)
        l0 = np.linalg.norm(v1 - v0)
        l1 = np.linalg.norm(v2 - v1)
        l2 = np.linalg.norm(v3 - v2)
        l3 = np.linalg.norm(v0 - v3)
        u_len = 0.5 * (l0 + l2)
        v_len = 0.5 * (l1 + l3)
        ar = max(u_len, v_len) / max(min(u_len, v_len), 1e-7)
        if ar > 3.5:
            # Revert added inset verts
            for iv in inset_verts:
                mesh.remove_vert(iv)
            return {"ok": False, "reason": f"cap quad aspect ratio {ar:.2f} > 3.5"}

    for f in new_faces:
        mesh.add_face(f)

    return {"ok": True, "loop_len": n, "bevel_quads": n, "chord_quads": half - 1}


def cap_all_planar_boundaries(mesh, min_loop_len=4):
    """Find closed boundary loops and cap the planar, even-length ones."""
    boundary_edges = mesh.boundary_edges()
    visited = set()
    results = []

    for seed in boundary_edges:
        if seed in visited:
            continue
        loop = []
        stack = [seed]
        local_visited = {seed}
        while stack:
            e = stack.pop()
            loop.append(e)
            for v in mesh.edge_verts(e):
                for e2 in mesh.link_edges(v):
                    if mesh.is_boundary(e2) and e2 not in local_visited:
                        local_visited.add(e2)
                        stack.append(e2)
        visited |= local_visited

        if len(loop) < min_loop_len:
            continue
        result = cap_boundary_loop(mesh, loop)
        result["loop_edge_count"] = len(loop)
        results.append(result)

    # Newly created faces (bevel ring + chord strips) are built with a fixed
    # vertex order that isn't guaranteed to match the surrounding mesh's
    # existing winding — normalize after this stage specifically creates
    # new faces (same fix_winding.py handles the general case; recalculating
    # normals alone isn't enough to repair actual winding inconsistency, but
    # this keeps face.normal() cache correct for any stage run right after).
    if results:
        mesh.recalc_face_normals()

    return results


def cap_obj_file(in_obj, out_obj):
    mesh = io_mesh.load(in_obj)
    results = cap_all_planar_boundaries(mesh)
    io_mesh.export(out_obj, mesh, quads=True)
    return {"out_obj": out_obj, "loops": results}


def self_test():
    """Synthetic 16-gon planar circular boundary — must cap with ZERO
    triangles and no center pole (the exact pattern this module targets).
    """
    mesh = EditMesh()
    n = 16
    top = []
    bottom = []
    for i in range(n):
        theta = 2 * math.pi * i / n
        top.append(mesh.add_vert((math.cos(theta), math.sin(theta), 0.0)))
        bottom.append(mesh.add_vert((math.cos(theta), math.sin(theta), -0.3)))
    # Side wall quads make the top ring a genuine boundary loop (each top
    # edge touches exactly 1 face); bottom is left open too but unrelated
    # to this test.
    for i in range(n):
        j = (i + 1) % n
        mesh.add_face([top[i], top[j], bottom[j], bottom[i]])

    results = cap_all_planar_boundaries(mesh)
    n_tris = sum(1 for f in mesh.faces if len(mesh.face_verts(f)) == 3)
    n_quads = sum(1 for f in mesh.faces if len(mesh.face_verts(f)) == 4)
    n_faces = len(list(mesh.faces))
    out = {
        "results": results,
        "n_faces": n_faces,
        "n_quads": n_quads,
        "n_tris": n_tris,
        "quad_pct": 100.0 * n_quads / max(1, n_faces),
    }
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--self-test":
        result = self_test()
        print("CAPS_SELFTEST_JSON_START")
        print(json.dumps(result, indent=2))
        print("CAPS_SELFTEST_JSON_END")
    elif len(args) >= 2:
        result = cap_obj_file(args[0], args[1])
        print("CAPS_RESULT_JSON_START")
        print(json.dumps(result, indent=2))
        print("CAPS_RESULT_JSON_END")
    else:
        print("Usage: python3 caps.py --self-test")
        print("   or: python3 caps.py <in.obj> <out.obj>")
        sys.exit(1)
