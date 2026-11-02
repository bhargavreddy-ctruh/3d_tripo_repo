"""General coplanar-region merge — the fix for the "stale/unnecessary
edges" defect found 2026-11-01: `dissolve.py`'s transverse-loop tracer only
continues through exactly-valence-4 vertices (very common NOT to be, per
measurement: valence-3 is nearly as common as valence-4 on real remeshed
output), and `darts.py` only merges triangle+triangle pairs. Neither can
touch a quad+quad, quad+n-gon, or n-gon+n-gon pair even when perfectly
coplanar. Measured directly on real output: 30.9% of the wooden rack's and
9.0% of the sofa's interior edges were between two faces differing by
<2 degrees and were NOT a triangle pair — i.e. genuinely unnecessary edges
neither existing stage could remove.

This stage removes that limitation entirely: flood-fill connected faces
into coplanar clusters (bounded by protect.py's hard-protected edges, so a
real feature is never crossed), then hand each cluster to bmesh's own
`dissolve_faces`, which merges a set of faces into the minimal face(s)
describing their combined boundary — regardless of vertex valence or
original face shape. Because this operates on the real shared mesh
topology (not an independent per-cluster 2D re-triangulation, which is
what caused the old tripo-logic-approach-v2 coplanar_merge.py's duplicate-
triangle-at-a-shared-corner bug), a vertex shared by multiple clusters is
simply one shared BMVert throughout — there is no reconstruction-from-
scratch step where two clusters could independently disagree about it.
Runs under Blender (bpy/bmesh).
"""

import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy
import bmesh

import config
import io_blender


def find_coplanar_clusters(bm, angle_tol_deg=2.0):
    """BFS over faces: cross an edge only if it's a manifold interior edge
    (never a boundary) and the two adjacent faces' normals differ by less
    than angle_tol_deg.

    Deliberately does NOT reuse protect.py's hard_protected set here: that
    set's dome/saddle rule is vertex-level (protects a whole neighborhood
    around a suspected pole) and, measured directly, becomes noisy and
    over-triggers once the mesh has already been through dissolve/darts
    (their non-planar merged n-gons have less reliable Newell normals,
    which the dome/saddle rule's mean-deviation check picks up as false
    "poles" -- confirmed: 72% of the rack's edges were dome/saddle-flagged
    despite it being a mostly flat box). For THIS stage, the direct
    per-edge dihedral-angle test at a tight tolerance (far stricter than
    protect.py's 18deg crease threshold) is itself a sufficient, more
    reliable safety check: an edge straddling anything that is not
    genuinely coplanar simply won't pass the angle test at all.
    """
    angle_tol_rad = math.radians(angle_tol_deg)
    bm.faces.ensure_lookup_table()

    visited = set()
    clusters = []
    for seed in bm.faces:
        if seed in visited:
            continue
        cluster = []
        stack = [seed]
        visited.add(seed)
        while stack:
            f = stack.pop()
            cluster.append(f)
            if f.normal.length < 1e-9:
                continue
            for e in f.edges:
                if e.is_boundary or len(e.link_faces) != 2:
                    continue
                other = e.link_faces[0] if e.link_faces[1] == f else e.link_faces[1]
                if other in visited:
                    continue
                if other.normal.length < 1e-9:
                    continue
                ang = f.normal.angle(other.normal)
                if ang < angle_tol_rad:
                    visited.add(other)
                    stack.append(other)
        clusters.append(cluster)
    return clusters


def _is_disk_topology(cluster_faces):
    """A cluster is safe to dissolve into one n-gon only if its boundary
    (the edges not shared between two cluster faces) forms exactly ONE
    simple cycle. A cluster with an internal hole, a pinch point, or more
    than one boundary loop would make dissolve_faces create a real hole
    (observed directly: one such cluster grew the mesh's boundary-edge
    count by 3) -- cheaper and more reliable to detect this up front than
    to catch it after the fact.
    """
    face_set = set(cluster_faces)
    boundary_edges = set()
    for f in cluster_faces:
        for e in f.edges:
            internal = sum(1 for lf in e.link_faces if lf in face_set)
            if internal < 2:
                boundary_edges.add(e)

    if not boundary_edges:
        return False  # a closed cluster with no boundary at all -- not a disk

    # Walk the boundary edges via shared vertices; a single simple cycle
    # visits every boundary edge exactly once and returns to the start.
    adjacency = {}
    for e in boundary_edges:
        for v in e.verts:
            adjacency.setdefault(v, []).append(e)

    start_edge = next(iter(boundary_edges))
    visited = {start_edge}
    v = start_edge.verts[0]
    cur = start_edge
    steps = 0
    while True:
        nxt_candidates = [e for e in adjacency.get(cur.other_vert(v), [])
                           if e not in visited]
        if not nxt_candidates:
            break
        nxt = nxt_candidates[0]
        visited.add(nxt)
        v = cur.other_vert(v)
        cur = nxt
        steps += 1
        if steps > len(boundary_edges) + 1:
            return False  # degenerate walk, bail out safely

    return len(visited) == len(boundary_edges)


def dissolve_collinear_vertices(bm, angle_tol_deg=1.0):
    """Remove any valence-2 vertex whose two remaining edges point in
    nearly opposite directions (i.e. it sits exactly on the straight line
    between its two neighbors). Only meaningful AFTER a coplanar merge has
    already removed the internal edges of a flat cluster: a vertex that
    used to be shared by several small faces on a straight run can be left
    with exactly 2 edges on the merged face's boundary, genuinely
    redundant. This is exact, not an approximation -- a vertex measured as
    collinear lies exactly on the line through its neighbors, so removing
    it changes nothing about the surface, only the vertex/edge count.
    Only used by the pre-remesh pass (`collapse_collinear=True`); the
    existing post-remesh call site leaves vertices alone (unchanged
    behavior) since later stages may still need them.
    """
    # PERFORMANCE BUG, found via a real timing test (854k-face rack
    # component never finished in 17+ minutes): the original version of
    # this function did `while changed: for v in bm.verts: ...`, restarting
    # a full O(V) scan after EVERY single vertex dissolve -- O(V^2) overall
    # on a mesh with tens of thousands of collinear vertices. Fixed to
    # collect all currently-valid candidates in ONE scan per pass, dissolve
    # them all, and only re-scan a small bounded number of times (removing
    # one vertex can expose a newly-collinear neighbor, but that chains at
    # most a few vertices deep in practice, not the whole mesh).
    angle_tol_rad = math.radians(angle_tol_deg)
    cos_thresh = -math.cos(angle_tol_rad)
    n_removed = 0

    for _pass in range(10):
        bm.verts.ensure_lookup_table()
        candidates = []
        for v in bm.verts:
            if len(v.link_edges) != 2:
                continue
            e0, e1 = v.link_edges
            if e0.is_boundary != e1.is_boundary:
                continue  # don't mix a true mesh boundary edge with an interior one
            other0 = e0.other_vert(v)
            other1 = e1.other_vert(v)
            dir0 = (other0.co - v.co)
            dir1 = (other1.co - v.co)
            if dir0.length < 1e-9 or dir1.length < 1e-9:
                continue
            dir0.normalize()
            dir1.normalize()
            if dir0.dot(dir1) < cos_thresh:
                candidates.append(v)

        if not candidates:
            break

        try:
            bmesh.ops.dissolve_verts(bm, verts=candidates)
            n_removed += len(candidates)
        except Exception:
            # A batch dissolve can fail if two candidates interact badly;
            # fall back to one-at-a-time for just this pass rather than
            # losing the whole batch.
            for v in candidates:
                if not v.is_valid:
                    continue
                try:
                    bmesh.ops.dissolve_verts(bm, verts=[v])
                    n_removed += 1
                except Exception:
                    pass
    return n_removed


def merge_coplanar_regions(bm, angle_tol_deg=2.0, collapse_collinear=False,
                            collinear_angle_tol_deg=1.0):
    """Mutates bm in place. Returns stats dict."""
    t0 = time.perf_counter()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    t_normals = time.perf_counter()

    n_boundary_before = sum(1 for e in bm.edges if e.is_boundary)
    n_faces_before = len(bm.faces)

    clusters = find_coplanar_clusters(bm, angle_tol_deg=angle_tol_deg)
    multi_face_clusters = [c for c in clusters if len(c) > 1]
    t_flood_fill = time.perf_counter()
    print(f"[coplanar_merge] recalc_normals={t_normals-t0:.2f}s "
          f"flood_fill={t_flood_fill-t_normals:.2f}s "
          f"({len(clusters)} clusters, {len(multi_face_clusters)} multi-face, "
          f"largest={max((len(c) for c in multi_face_clusters), default=0)})",
          flush=True)

    n_merged = 0
    n_skipped_exception = 0
    n_skipped_non_disk = 0
    for _ci, cluster in enumerate(multi_face_clusters):
        valid_faces = [f for f in cluster if f.is_valid]
        if len(valid_faces) < 2:
            continue
        if not _is_disk_topology(valid_faces):
            # An annulus/multiply-connected/branching cluster would create a
            # real hole if dissolved (confirmed directly: one such cluster
            # grew the mesh's boundary-edge count by 3) -- skip it rather
            # than risk corruption, found BEFORE attempting the dissolve.
            n_skipped_non_disk += 1
            continue
        try:
            # use_verts=False deliberately: True lets dissolve_faces delete
            # a now-"redundant" (e.g. collinear) vertex, but if that vertex
            # is ALSO used by a face OUTSIDE this cluster (common at a
            # T-junction where 3+ faces meet but not all are in the
            # cluster), deleting it corrupts that other face -- confirmed
            # directly: a trivial 2-face cluster that passed the disk-
            # topology check still grew the mesh's boundary by 3 edges with
            # use_verts=True. With use_verts=False no vertex is ever
            # removed, so the only edges touched are the cluster's own
            # strictly-internal ones (never a boundary edge by
            # construction) -- provably safe.
            bmesh.ops.dissolve_faces(bm, faces=valid_faces, use_verts=False)
            n_merged += 1
        except Exception:
            n_skipped_exception += 1

    t_dissolve = time.perf_counter()
    print(f"[coplanar_merge] dissolve_faces_loop={t_dissolve-t_flood_fill:.2f}s "
          f"({n_merged} merged)", flush=True)

    n_collinear_removed = 0
    if collapse_collinear:
        n_collinear_removed = dissolve_collinear_vertices(
            bm, angle_tol_deg=collinear_angle_tol_deg)
    t_collinear = time.perf_counter()
    print(f"[coplanar_merge] collinear_cleanup={t_collinear-t_dissolve:.2f}s "
          f"({n_collinear_removed} removed)", flush=True)

    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    n_boundary_after = sum(1 for e in bm.edges if e.is_boundary)

    if n_boundary_after > n_boundary_before:
        raise RuntimeError(
            f"coplanar_merge: boundary edges grew {n_boundary_before} -> "
            f"{n_boundary_after} -- a real hole, rejecting."
        )

    return {
        "clusters_found": len(clusters),
        "multi_face_clusters": len(multi_face_clusters),
        "clusters_merged": n_merged,
        "clusters_skipped_non_disk": n_skipped_non_disk,
        "clusters_skipped_exception": n_skipped_exception,
        "collinear_verts_removed": n_collinear_removed,
        "faces_before": n_faces_before,
        "faces_after": len(bm.faces),
        "verts_after": len(bm.verts),
        "boundary_before": n_boundary_before,
        "boundary_after": n_boundary_after,
    }


def merge_obj_file(in_obj, out_obj, angle_tol_deg=2.0, collapse_collinear=False,
                    export_quads=True):
    io_blender.clear_scene()
    objs = io_blender.import_mesh(in_obj)
    obj = objs[0]
    bm = bmesh.new()
    bm.from_mesh(obj.data)

    stats = merge_coplanar_regions(bm, angle_tol_deg=angle_tol_deg,
                                    collapse_collinear=collapse_collinear)

    bm.to_mesh(obj.data)
    obj.data.update()
    bm.free()
    io_blender.export_mesh(out_obj, objects=[obj], quads=export_quads)
    stats["out_obj"] = out_obj
    return stats


if __name__ == "__main__":
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    if len(args) < 2:
        print("Usage: blender --background --python coplanar_merge.py -- <in.obj> <out.obj> [--collapse-collinear]")
        sys.exit(1)
    collapse = "--collapse-collinear" in args
    stats = merge_obj_file(args[0], args[1], collapse_collinear=collapse)
    print("COPLANAR_MERGE_RESULT_JSON_START")
    print(json.dumps(stats, indent=2))
    print("COPLANAR_MERGE_RESULT_JSON_END")
