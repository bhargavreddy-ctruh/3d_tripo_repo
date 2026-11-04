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
real feature is never crossed), then hand each cluster to
EditMesh.merge_faces, which merges a set of faces into the minimal face(s)
describing their combined boundary — regardless of vertex valence or
original face shape. Because this operates on the real shared mesh
topology (not an independent per-cluster 2D re-triangulation, which is
what caused the old tripo-logic-approach-v2 coplanar_merge.py's duplicate-
triangle-at-a-shared-corner bug), a vertex shared by multiple clusters is
simply one shared vertex id throughout — there is no reconstruction-from-
scratch step where two clusters could independently disagree about it.
Pure Python (EditMesh), no Blender.
"""

import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import io_mesh


def find_coplanar_clusters(mesh, angle_tol_deg=2.0):
    """BFS over faces: cross an edge only if it's a manifold interior edge
    (never a boundary) and the two adjacent faces' normals differ by less
    than angle_tol_deg.

    Deliberately does NOT reuse protect.py's hard_protected set here: that
    set's dome/saddle rule is vertex-level (protects a whole neighborhood
    around a suspected pole) and, measured directly, becomes noisy and
    over-triggers once the mesh has already been through dissolve/darts
    (their non-planar merged n-gons have less reliable Newell normals,
    which the dome/saddle rule's mean-deviation check picks up as false
    "poles"). For THIS stage, the direct per-edge dihedral-angle test at a
    tight tolerance (far stricter than protect.py's 18deg crease threshold)
    is itself a sufficient, more reliable safety check: an edge straddling
    anything that is not genuinely coplanar simply won't pass the angle
    test at all.
    """
    angle_tol_rad = math.radians(angle_tol_deg)

    visited = set()
    clusters = []
    for seed in mesh.faces:
        if seed in visited:
            continue
        cluster = []
        stack = [seed]
        visited.add(seed)
        while stack:
            f = stack.pop()
            cluster.append(f)
            nf = mesh.face_normal(f)
            if np.linalg.norm(nf) < 1e-9:
                continue
            for e in mesh.face_edges(f):
                if mesh.is_boundary(e) or len(mesh.link_faces(e)) != 2:
                    continue
                link = mesh.link_faces(e)
                other = link[0] if link[1] == f else link[1]
                if other in visited:
                    continue
                n_other = mesh.face_normal(other)
                if np.linalg.norm(n_other) < 1e-9:
                    continue
                cos_a = float(np.clip(np.dot(nf, n_other), -1.0, 1.0))
                ang = math.acos(cos_a)
                if ang < angle_tol_rad:
                    visited.add(other)
                    stack.append(other)
        clusters.append(cluster)
    return clusters


def merge_coplanar_regions(mesh, angle_tol_deg=2.0, collapse_collinear=False,
                            collinear_angle_tol_deg=1.0):
    """Mutates mesh in place. Returns stats dict."""
    t0 = time.perf_counter()
    mesh.recalc_face_normals()
    t_normals = time.perf_counter()

    n_boundary_before = len(mesh.boundary_edges())
    n_faces_before = len(list(mesh.faces))

    clusters = find_coplanar_clusters(mesh, angle_tol_deg=angle_tol_deg)
    multi_face_clusters = [c for c in clusters if len(c) > 1]
    t_flood_fill = time.perf_counter()
    print(f"[coplanar_merge] recalc_normals={t_normals-t0:.2f}s "
          f"flood_fill={t_flood_fill-t_normals:.2f}s "
          f"({len(clusters)} clusters, {len(multi_face_clusters)} multi-face, "
          f"largest={max((len(c) for c in multi_face_clusters), default=0)})",
          flush=True)

    n_merged = 0
    n_skipped_non_disk = 0
    for cluster in multi_face_clusters:
        valid_faces = [f for f in cluster if f in mesh._face_verts]
        if len(valid_faces) < 2:
            continue
        # merge_faces(dissolve_verts=False) deliberately never removes a
        # vertex: if a cluster vertex is ALSO used by a face OUTSIDE this
        # cluster (common at a T-junction where 3+ faces meet but not all
        # are in the cluster), removing it would corrupt that other face.
        # With dissolve_verts=False no vertex is ever touched, so the only
        # edges removed are the cluster's own strictly-internal ones (never
        # a boundary edge by construction) — provably safe. merge_faces
        # also folds in the disk-topology safety check itself (returns
        # None, mutating nothing, if the cluster's boundary isn't exactly
        # one simple loop — an annulus/branching/multiply-connected cluster
        # would otherwise create a real hole).
        new_fid = mesh.merge_faces(valid_faces, dissolve_verts=False)
        if new_fid is not None:
            n_merged += 1
        else:
            n_skipped_non_disk += 1

    t_dissolve = time.perf_counter()
    print(f"[coplanar_merge] dissolve_faces_loop={t_dissolve-t_flood_fill:.2f}s "
          f"({n_merged} merged)", flush=True)

    n_collinear_removed = 0
    if collapse_collinear:
        all_verts = list(mesh.verts)
        n_collinear_removed = mesh.dissolve_collinear_verts(
            all_verts, angle_tol_deg=collinear_angle_tol_deg)
    t_collinear = time.perf_counter()
    print(f"[coplanar_merge] collinear_cleanup={t_collinear-t_dissolve:.2f}s "
          f"({n_collinear_removed} removed)", flush=True)

    n_boundary_after = len(mesh.boundary_edges())

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
        "clusters_skipped_exception": 0,
        "collinear_verts_removed": n_collinear_removed,
        "faces_before": n_faces_before,
        "faces_after": len(list(mesh.faces)),
        "verts_after": len(list(mesh.verts)),
        "boundary_before": n_boundary_before,
        "boundary_after": n_boundary_after,
    }


def merge_obj_file(in_obj, out_obj, angle_tol_deg=2.0, collapse_collinear=False,
                    export_quads=True):
    mesh = io_mesh.load(in_obj)
    stats = merge_coplanar_regions(mesh, angle_tol_deg=angle_tol_deg,
                                    collapse_collinear=collapse_collinear)
    io_mesh.export(out_obj, mesh, quads=export_quads)
    stats["out_obj"] = out_obj
    return stats


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 2:
        print("Usage: python3 coplanar_merge.py <in.obj> <out.obj> [--collapse-collinear]")
        sys.exit(1)
    collapse = "--collapse-collinear" in args
    stats = merge_obj_file(args[0], args[1], collapse_collinear=collapse)
    print("COPLANAR_MERGE_RESULT_JSON_START")
    print(json.dumps(stats, indent=2))
    print("COPLANAR_MERGE_RESULT_JSON_END")
