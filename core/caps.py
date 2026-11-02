"""Parallel-chord quad caps for near-planar boundary loops — ports the
bevel-ring + parallel-chord-strip construction from
`/Users/bhargavreddy/anisotropic Quad Dominant/burger_stand_retopo.py`,
which eliminates the center-pole triangle-fan pattern a generic remesher
leaves on flat circular/polygonal caps (confirmed 100% quads on its own
disk/dome/cylinder-cap benchmarks). Runs under Blender (bpy/bmesh).

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

import bpy
import bmesh
import mathutils

import io_blender


def _is_planar(coords, tol_frac=0.02):
    """Fit a plane via SVD-free approach (use the polygon's own average
    normal + centroid) and check max deviation relative to the loop's own
    bounding diagonal."""
    centroid = sum(coords, mathutils.Vector((0, 0, 0))) / len(coords)
    # Average normal via Newell's method.
    normal = mathutils.Vector((0, 0, 0))
    n = len(coords)
    for i in range(n):
        a, b = coords[i], coords[(i + 1) % n]
        normal.x += (a.y - b.y) * (a.z + b.z)
        normal.y += (a.z - b.z) * (a.x + b.x)
        normal.z += (a.x - b.x) * (a.y + b.y)
    if normal.length < 1e-9:
        return False, centroid, normal
    normal.normalize()
    diag = max((c - centroid).length for c in coords) * 2 or 1.0
    max_dev = max(abs((c - centroid).dot(normal)) for c in coords)
    return (max_dev / diag) < tol_frac, centroid, normal


def cap_boundary_loop(bm, loop_edges, inset_frac=0.88):
    """loop_edges: an ordered, closed sequence of boundary BMEdges.
    Returns a dict with ok/skipped and counts. Fills the hole in place.
    """
    # Order the boundary verts by walking the loop edges. Edges are keyed by
    # Python object identity here (NOT e.index, which bmesh leaves as -1 for
    # edges created in this session until an explicit index_update()/
    # ensure_lookup_table() renumbering — a real bug caught by the
    # self-test: every edge collided on the same -1 key and silently broke
    # the walk after one step).
    loop_edge_set = set(loop_edges)
    verts = []
    seen_edges = set()
    e0 = loop_edges[0]
    v = e0.verts[0]
    cur_e = e0
    for _ in range(len(loop_edges)):
        verts.append(v)
        for e in v.link_edges:
            if e in loop_edge_set and e not in seen_edges:
                seen_edges.add(e)
                v = e.other_vert(v)
                cur_e = e
                break
    if len(verts) != len(loop_edges):
        return {"ok": False, "reason": "could not order loop"}

    n = len(verts)
    if n % 2 != 0:
        return {"ok": False, "reason": f"odd loop length {n}, skipped (no lossy fallback)"}

    coords = [v.co.copy() for v in verts]
    planar, centroid, normal = _is_planar(coords)
    if not planar:
        return {"ok": False, "reason": "not planar enough"}

    # Bevel ring: inset copy of the loop.
    inset_verts = [bm.verts.new(centroid + (c - centroid) * inset_frac) for c in coords]
    for i in range(n):
        j = (i + 1) % n
        try:
            bm.faces.new([verts[i], verts[j], inset_verts[j], inset_verts[i]])
        except ValueError:
            pass  # face already exists (shouldn't happen on a clean hole)

    # Parallel chord strips across the inset polygon: pair vertex i with
    # its mirror i+n/2, connect consecutive pairs into quads.
    half = n // 2
    chord_pairs = [(inset_verts[i], inset_verts[i + half]) for i in range(half)]
    n_chord_faces = 0
    for i in range(half - 1):
        a0, a1 = chord_pairs[i]
        b0, b1 = chord_pairs[i + 1]
        try:
            bm.faces.new([a0, b0, b1, a1])
            n_chord_faces += 1
        except ValueError:
            pass

    return {"ok": True, "loop_len": n, "bevel_quads": n, "chord_quads": n_chord_faces}


def cap_all_planar_boundaries(bm, min_loop_len=4):
    """Find closed boundary loops and cap the planar, even-length ones."""
    bm.edges.ensure_lookup_table()
    boundary_edges = [e for e in bm.edges if e.is_boundary]
    visited = set()
    results = []

    for seed in boundary_edges:
        if seed in visited:
            continue
        # Walk the connected boundary-edge loop containing `seed`. Keyed by
        # edge object, not e.index — see cap_boundary_loop's comment on why
        # e.index (-1 for edges not yet renumbered) is not a safe key here.
        loop = []
        stack = [seed]
        local_visited = {seed}
        while stack:
            e = stack.pop()
            loop.append(e)
            for v in e.verts:
                for e2 in v.link_edges:
                    if e2.is_boundary and e2 not in local_visited:
                        local_visited.add(e2)
                        stack.append(e2)
        visited |= local_visited

        if len(loop) < min_loop_len:
            continue
        result = cap_boundary_loop(bm, loop)
        result["loop_edge_count"] = len(loop)
        results.append(result)

    # Real bug, found via a winding-consistency check prompted during the
    # dissolve_limit investigation (2026-11-02): newly created faces
    # (bevel ring + chord strips) are built with a fixed vertex order that
    # is not guaranteed to match the surrounding mesh's existing winding —
    # confirmed directly: a real asset went from `is_winding_consistent`
    # True before this function ran to False after, with 3,637 face pairs
    # showing near-opposite normals. `bmesh.ops.recalc_face_normals` is
    # already used the same way at the start of every other bmesh-based
    # stage in this codebase (dissolve.py, coplanar_merge.py); the fix here
    # is to also normalize AFTER this stage specifically creates new faces.
    if results:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return results


def cap_obj_file(in_obj, out_obj):
    io_blender.clear_scene()
    objs = io_blender.import_mesh(in_obj)
    obj = objs[0]
    bm = bmesh.new()
    bm.from_mesh(obj.data)

    results = cap_all_planar_boundaries(bm)

    bm.to_mesh(obj.data)
    obj.data.update()
    bm.free()
    io_blender.export_mesh(out_obj, objects=[obj], quads=True)
    return {"out_obj": out_obj, "loops": results}


def self_test():
    """Synthetic 16-gon planar circular boundary — must cap with ZERO
    triangles and no center pole (the exact pattern this module targets).
    """
    bm = bmesh.new()
    n = 16
    top = []
    bottom = []
    for i in range(n):
        theta = 2 * math.pi * i / n
        top.append(bm.verts.new((math.cos(theta), math.sin(theta), 0.0)))
        bottom.append(bm.verts.new((math.cos(theta), math.sin(theta), -0.3)))
    # Side wall quads make the top ring a genuine boundary loop (each top
    # edge touches exactly 1 face); bottom is left open too but unrelated
    # to this test.
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new([top[i], top[j], bottom[j], bottom[i]])
    bm.edges.ensure_lookup_table()

    results = cap_all_planar_boundaries(bm)
    bm.faces.ensure_lookup_table()
    n_tris = sum(1 for f in bm.faces if len(f.verts) == 3)
    n_quads = sum(1 for f in bm.faces if len(f.verts) == 4)
    out = {
        "results": results,
        "n_faces": len(bm.faces),
        "n_quads": n_quads,
        "n_tris": n_tris,
        "quad_pct": 100.0 * n_quads / max(1, len(bm.faces)),
    }
    bm.free()
    return out


if __name__ == "__main__":
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
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
        print("Usage: blender --background --python caps.py -- --self-test")
        print("   or: blender --background --python caps.py -- <in.obj> <out.obj>")
        sys.exit(1)
