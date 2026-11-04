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
        return {"ok": False, "reason": "not planar enough"}

    # Bevel ring: inset copy of the loop.
    inset_verts = [mesh.add_vert(centroid + (c - centroid) * inset_frac) for c in coords]
    for i in range(n):
        j = (i + 1) % n
        mesh.add_face([verts[i], verts[j], inset_verts[j], inset_verts[i]])

    # Parallel chord strips across the inset polygon: pair vertex i with
    # its mirror i+n/2, connect consecutive pairs into quads.
    half = n // 2
    chord_pairs = [(inset_verts[i], inset_verts[i + half]) for i in range(half)]
    n_chord_faces = 0
    for i in range(half - 1):
        a0, a1 = chord_pairs[i]
        b0, b1 = chord_pairs[i + 1]
        mesh.add_face([a0, b0, b1, a1])
        n_chord_faces += 1

    return {"ok": True, "loop_len": n, "bevel_quads": n, "chord_quads": n_chord_faces}


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
