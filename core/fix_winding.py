"""BMesh-native winding-consistency fix — stays within bpy/bmesh so it
preserves quad/n-gon topology (unlike trimesh.repair.fix_winding, which
only works on trimesh.Trimesh and therefore forces full triangulation on
load, destroying everything coplanar_merge/darts/caps already built).

Found necessary 2026-11-02: caps.py creating new faces (bevel ring + chord
strips) can leave a mesh's winding inconsistent, and a whole-mesh
bmesh.ops.recalc_face_normals call does NOT always fix it (confirmed: a
real decimation-fallback asset with 95 non-manifold edges stayed
inconsistent after recalc_face_normals). This flood-fills face winding
consistency via edge-direction comparison instead, the same algorithm
trimesh's own repair uses, skipping non-manifold edges (>2 or <2 link
faces) as traversal edges since there's no single well-defined consistent
choice across a genuine non-manifold junction — a safe, bounded best
effort, not a claim of full global consistency on non-manifold topology.
"""
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy
import bmesh


def fix_winding_consistency(bm):
    """Returns number of faces flipped; mutates bm in exactly ONE batched
    `bmesh.ops.reverse_faces` call at the very end.

    Deliberately split into a pure DECISION phase (no mesh mutation at all)
    followed by a single APPLY phase. Found necessary directly: an earlier
    version called `bmesh.ops.reverse_faces` incrementally WHILE iterating
    `edge.link_faces` mid-traversal, which never completed in 5+ CPU-minutes
    on a real ~97k-face mesh — mutating bmesh connectivity data while a
    live iterator over that same connectivity is still in use is unsafe and
    was the real cause, not raw algorithmic cost (confirmed: the pure
    decision pass below, with no mutation until the very end, completes
    quickly on the same mesh).

    Propagates through any edge with >=2 linked faces (not just exactly 2):
    a genuine non-manifold junction (3+ faces sharing an edge) has no single
    globally "correct" choice, but still comparing against each unvisited
    linked face keeps the traversal graph connected far better than
    skipping those edges outright (skipping them left most of a real
    asset's faces unreachable from the seed in an earlier attempt). A true
    boundary edge (exactly 1 linked face) is still skipped — nothing to
    compare against.

    Caches each face's (vertex -> local index) map once instead of
    rebuilding `list(face.verts)` and linear-searching it on every edge
    check — meaningful on faces up to 45-sided seen in real output.
    """
    bm.faces.ensure_lookup_table()
    vert_index_cache = {}

    def vert_map(face):
        m = vert_index_cache.get(face)
        if m is None:
            verts = list(face.verts)
            m = ({v: i for i, v in enumerate(verts)}, verts)
            vert_index_cache[face] = m
        return m

    def raw_forward(face, a, b):
        idx, verts = vert_map(face)
        n = len(verts)
        return verts[(idx[a] + 1) % n] is b

    flip_decision = {}
    visited = set()

    for seed in bm.faces:
        if seed in visited:
            continue
        visited.add(seed)
        flip_decision[seed] = False
        stack = [seed]
        while stack:
            f = stack.pop()
            for e in f.edges:
                if len(e.link_faces) < 2:
                    continue
                a, b = e.verts[0], e.verts[1]
                f_eff = raw_forward(f, a, b) != flip_decision[f]
                for other in e.link_faces:
                    if other is f or other in visited:
                        continue
                    visited.add(other)
                    other_raw = raw_forward(other, a, b)
                    # Consistent winding needs opposite traversal directions.
                    flip_decision[other] = (other_raw == f_eff)
                    stack.append(other)

    faces_to_flip = [f for f, flip in flip_decision.items() if flip]
    if faces_to_flip:
        bmesh.ops.reverse_faces(bm, faces=faces_to_flip)
    return len(faces_to_flip)


if __name__ == "__main__":
    import json
    import io_blender

    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    if len(args) < 2:
        print("Usage: blender --background --python fix_winding.py -- <in.obj> <out.obj>")
        sys.exit(1)

    io_blender.clear_scene()
    objs = io_blender.import_mesh(args[0])
    obj = objs[0]
    bm = bmesh.new()
    bm.from_mesh(obj.data)

    n_flipped = fix_winding_consistency(bm)

    bm.to_mesh(obj.data)
    obj.data.update()
    bm.free()
    io_blender.export_mesh(args[1], objects=[obj], quads=True)

    print("FIX_WINDING_RESULT_JSON_START")
    print(json.dumps({"faces_flipped": n_flipped, "out_obj": args[1]}, indent=2))
    print("FIX_WINDING_RESULT_JSON_END")
