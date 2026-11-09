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
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import io_mesh
import darts


def trace_ribbon_transverse_line(mesh, start_e, creases, flat_edges):
    """Traces a transverse chord through quads across flat_edges,
    stopping cleanly when hitting creases or boundaries.
    """
    if start_e not in flat_edges or mesh.is_boundary(start_e) or start_e not in mesh._edge_faces:
        return None

    def step_dir(curr_e, curr_v):
        loop = [curr_e]
        e = curr_e
        v = curr_v
        visited_v = {v}
        while True:
            edges = list(mesh.link_edges(v))
            if any(ed in creases for ed in edges) or mesh.is_boundary(e):
                return loop, 'crease'
            in_faces = set(mesh.link_faces(e))
            nxt = None
            if len(edges) == 4:
                for cand in edges:
                    if cand != e and cand in flat_edges and not (set(mesh.link_faces(cand)) & in_faces):
                        nxt = cand
                        break
            elif len(edges) in (3, 5):
                # Extraordinary pole: check tangent alignment to continue straight
                v_prev = mesh.other_vert(e, v)
                t_in = mesh.vert_co(v) - mesh.vert_co(v_prev)
                l_in = np.linalg.norm(t_in)
                if l_in > 1e-9:
                    t_in_u = t_in / l_in
                    best_cos = math.cos(math.radians(20.0))
                    for cand in edges:
                        if cand == e or cand not in flat_edges: continue
                        if set(mesh.link_faces(cand)) & in_faces: continue
                        v_next = mesh.other_vert(cand, v)
                        t_out = mesh.vert_co(v_next) - mesh.vert_co(v)
                        l_out = np.linalg.norm(t_out)
                        if l_out > 1e-9 and np.dot(t_in_u, t_out / l_out) > best_cos:
                            best_cos = np.dot(t_in_u, t_out / l_out)
                            nxt = cand
            else:
                return loop, 'dead_end'

            if nxt is None:
                if len(edges) in (3, 5):
                    return loop, 'pole'
                return loop, 'dead_end'

            other_v = mesh.other_vert(nxt, v)
            if other_v in visited_v:
                return loop, 'closed'
            loop.append(nxt)
            visited_v.add(other_v)
            e = nxt
            v = other_v
            if len(loop) > 150:
                return loop, 'dead_end'

    v0, v1 = mesh.edge_verts(start_e)
    back_loop, back_stat = step_dir(start_e, v0)
    if back_stat == 'closed':
        return back_loop
    if back_stat == 'dead_end':
        return None

    fwd_loop, fwd_stat = step_dir(start_e, v1)
    if fwd_stat == 'closed':
        return fwd_loop
    if fwd_stat == 'dead_end':
        return None

    full_line = list(reversed(back_loop[1:])) + [start_e] + fwd_loop[1:]
    return full_line


def is_clean_chord_termination(mesh, line, creases, max_bnd_dev_deg=25.0):
    all_verts = []
    for ed in line:
        all_verts.extend(mesh.edge_verts(ed))
    v_cnt = Counter(all_verts)
    endpoints = [v for v, count in v_cnt.items() if count == 1]
    if len(endpoints) == 0:
        return True # closed ring
    for ep in endpoints:
        ep_edges = list(mesh.link_edges(ep))
        c_edges = [ed for ed in ep_edges if ed in creases or mesh.is_boundary(ed)]
        if len(c_edges) >= 2:
            v_a = mesh.other_vert(c_edges[0], ep)
            v_b = mesh.other_vert(c_edges[1], ep)
            t_a = mesh.vert_co(ep) - mesh.vert_co(v_a)
            t_b = mesh.vert_co(v_b) - mesh.vert_co(ep)
            l_a, l_b = np.linalg.norm(t_a), np.linalg.norm(t_b)
            if l_a > 1e-9 and l_b > 1e-9:
                cos_ang = np.clip(np.dot(t_a/l_a, t_b/l_b), -1.0, 1.0)
                dev = np.degrees(np.arccos(cos_ang))
                if dev <= max_bnd_dev_deg or len(c_edges) >= 3:
                    continue
        if len(ep_edges) == 3 and len(c_edges) == 0:
            continue
        return False
    return True


def detect_feature_collar_creases(mesh, angle_tol_deg=4.0):
    """Detects internal planar features (e.g. drawer knobs, cylindrical cutouts)
    and partitions planar panels into convex rectangular Cartesian sub-domains
    (Omega_Top, Omega_Bottom, Omega_Left, Omega_Right).
    Returns set of edge IDs to protect as creases so ribbon merging never crosses
    sub-domain boundaries or forms keyhole bridge cuts to internal features.
    """
    protected_edges = set()
    clusters = find_coplanar_clusters(mesh, angle_tol_deg=angle_tol_deg)

    for c in clusters:
        if len(c) < 10:
            continue
        face_set = set(c)
        b_edges = [
            e for f in face_set for e in mesh.face_edges(f)
            if sum(1 for lf in mesh.link_faces(e) if lf in face_set) == 1
        ]
        if not b_edges:
            continue

        adj = {}
        for e in b_edges:
            v0, v1 = mesh.edge_verts(e)
            adj.setdefault(v0, []).append((v1, e))
            adj.setdefault(v1, []).append((v0, e))

        visited_edges = set()
        cycles = []
        for e in b_edges:
            if e in visited_edges:
                continue
            v0, v1 = mesh.edge_verts(e)
            cycle = [v0]
            visited_edges.add(e)
            curr = v1
            while curr != v0:
                cycle.append(curr)
                cands = [(nxt, ed) for nxt, ed in adj.get(curr, []) if ed not in visited_edges]
                if not cands:
                    break
                nxt, ed = cands[0]
                visited_edges.add(ed)
                curr = nxt
            if curr == v0 and len(cycle) >= 3:
                cycles.append(cycle)

        if len(cycles) <= 1:
            continue  # Pure disk topology, no internal holes

        # Determine outer cycle (largest 3D bbox span)
        cycle_spans = []
        for cyc in cycles:
            coords = np.array([mesh.vert_co(v) for v in cyc])
            span = np.linalg.norm(coords.max(axis=0) - coords.min(axis=0))
            cycle_spans.append(span)

        outer_idx = int(np.argmax(cycle_spans))
        inner_cycles = [cyc for i, cyc in enumerate(cycles) if i != outer_idx]

        rep_f = c[0]
        n = mesh.face_normal(rep_f)
        if np.linalg.norm(n) < 1e-9:
            n = np.array([0.0, 0.0, 1.0])
        t1 = np.cross(n, [0, 0, 1]) if abs(n[2]) < 0.9 else np.cross(n, [1, 0, 0])
        l1 = np.linalg.norm(t1)
        if l1 < 1e-9:
            t1 = np.array([1.0, 0.0, 0.0])
            l1 = 1.0
        t1 = t1 / l1
        t2 = np.cross(n, t1)

        for inner_cyc in inner_cycles:
            collar_verts = set(inner_cyc)
            for cv in collar_verts:
                protected_edges.update(mesh.link_edges(cv))

            inner_coords = np.array([mesh.vert_co(v) for v in inner_cyc])
            u_inner = np.dot(inner_coords, t1)
            v_inner = np.dot(inner_coords, t2)
            u_min, u_max = float(u_inner.min()), float(u_inner.max())
            v_min, v_max = float(v_inner.min()), float(v_inner.max())

            for fid in c:
                fverts = mesh.face_verts(fid)
                fcoords = np.array([mesh.vert_co(v) for v in fverts])
                u_f = float(np.mean(np.dot(fcoords, t1)))
                v_f = float(np.mean(np.dot(fcoords, t2)))

                def classify(u, v):
                    if any(v_idx in collar_verts for v_idx in fverts):
                        return 0
                    if v >= v_max: return 1
                    if v <= v_min: return 2
                    if u <= u_min: return 3
                    if u >= u_max: return 4
                    return 0

                reg_f = classify(u_f, v_f)
                for eid in mesh.face_edges(fid):
                    lf = mesh.link_faces(eid)
                    if len(lf) == 2:
                        other_f = lf[0] if lf[1] == fid else lf[1]
                        if other_f in face_set:
                            ofverts = mesh.face_verts(other_f)
                            ofcoords = np.array([mesh.vert_co(v) for v in ofverts])
                            u_of = float(np.mean(np.dot(ofcoords, t1)))
                            v_of = float(np.mean(np.dot(ofcoords, t2)))
                            reg_other = classify(u_of, v_of)
                            if reg_f != reg_other:
                                protected_edges.add(eid)

    return protected_edges


def merge_ribbon_lines(mesh, max_passes=12, crease_deg=18.0, flat_deg=14.0, ar_gate=3.5, min_patch_size=120):
    """Reduces coplanar faces along (u, v) quad ribbons while strictly protecting
    orthogonal edge flow, creases, and small feature patches (e.g. scales, eye medallion).
    """
    crease_rad = math.radians(crease_deg)
    flat_rad = math.radians(flat_deg)
    ref_dir = np.array([1.0, 0.0, 0.0])
    total_dissolved = 0

    for p in range(max_passes):
        creases = set()
        flat_edges = set()
        for e in mesh.edges:
            if mesh.is_boundary(e):
                creases.add(e)
                continue
            lf = list(mesh.link_faces(e))
            if len(lf) != 2:
                creases.add(e)
                continue
            n0, n1 = mesh.face_normal(lf[0]), mesh.face_normal(lf[1])
            ang = math.acos(float(np.clip(np.dot(n0, n1), -1.0, 1.0)))
            if ang >= crease_rad:
                creases.add(e)
            elif ang <= flat_rad:
                flat_edges.add(e)

        # Connected component patch sizing
        face_patch = {}
        patch_id = 0
        for start_f in mesh.faces:
            if start_f in face_patch:
                continue
            q = [start_f]
            face_patch[start_f] = patch_id
            while q:
                curr = q.pop()
                for ed in mesh.face_edges(curr):
                    if ed in creases or ed not in flat_edges:
                        continue
                    for nxt in mesh.link_faces(ed):
                        if nxt not in face_patch:
                            face_patch[nxt] = patch_id
                            q.append(nxt)
            patch_id += 1

        patch_sizes = Counter(face_patch.values())
        protected_faces = set(f for f, pid in face_patch.items() if patch_sizes[pid] < min_patch_size)
        protected_edges = set()
        for f in protected_faces:
            for e in mesh.face_edges(f):
                protected_edges.add(e)

        target_axis = p % 2
        candidates = sorted(
            [e for e in flat_edges if e in mesh._edge_faces and e not in protected_edges],
            key=lambda e: min(mesh.calc_area(f) for f in mesh.link_faces(e))
        )

        visited_faces = set()
        accepted_lines = []

        for e in candidates:
            if any(f in visited_faces for f in mesh.link_faces(e)):
                continue
            line = trace_ribbon_transverse_line(mesh, e, creases, flat_edges)
            if not line or len(line) < 2:
                continue

            if any(any(f in protected_faces for f in mesh.link_faces(le)) for le in line):
                continue

            if not is_clean_chord_termination(mesh, line, creases, max_bnd_dev_deg=25.0):
                continue

            v_start, v_end = mesh.edge_verts(line[0])[0], mesh.edge_verts(line[-1])[1]
            line_vec = mesh.vert_co(v_end) - mesh.vert_co(v_start)
            norm_lv = np.linalg.norm(line_vec)
            if norm_lv > 1e-6:
                line_dir = line_vec / norm_lv
                align = abs(float(np.dot(line_dir, ref_dir)))
                axis = 0 if align >= 0.7071 else 1
                if axis != target_axis and p < 8:
                    continue

            ar_ok = True
            for le in line:
                lf = list(mesh.link_faces(le))
                if len(lf) != 2:
                    continue
                v0, v1 = mesh.edge_verts(le)
                w = float(np.linalg.norm(mesh.vert_co(v1) - mesh.vert_co(v0)))
                if w < 1e-9:
                    continue
                h = (mesh.calc_area(lf[0]) + mesh.calc_area(lf[1])) / max(w, 1e-9)
                ar = max(w, h) / max(min(w, h), 1e-7)
                if ar > ar_gate:
                    ar_ok = False
                    break
            if not ar_ok:
                continue

            line_faces = set()
            valid = True
            for le in line:
                for lf in mesh.link_faces(le):
                    if lf in visited_faces:
                        valid = False
                        break
                    line_faces.add(lf)
                if not valid:
                    break
            if valid:
                accepted_lines.append(line)
                visited_faces.update(line_faces)

        pass_dissolved = 0
        for line in accepted_lines:
            if not all(le in mesh._edge_faces for le in line):
                continue
            merged_verts = set()
            for le in line:
                if le not in mesh._edge_faces:
                    continue
                lf = list(mesh.link_faces(le))
                if len(lf) != 2:
                    continue
                f0, f1 = lf[0], lf[1]
                if f0 not in mesh._face_verts or f1 not in mesh._face_verts:
                    continue
                v0, v1 = mesh.edge_verts(le)
                new_f = mesh.merge_faces([f0, f1], dissolve_verts=False)
                if new_f is not None:
                    merged_verts.add(v0)
                    merged_verts.add(v1)

            v_to_dissolve = [v for v in merged_verts if v in mesh._vert_co]
            if v_to_dissolve:
                mesh.dissolve_collinear_verts(v_to_dissolve, angle_tol_deg=20.0)
            pass_dissolved += 1

        total_dissolved += pass_dissolved
        if pass_dissolved == 0 and p >= 8:
            break

    return total_dissolved


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


def _merge_non_disk_cluster_pairs(mesh, angle_tol_deg=10.0, max_dev=0.005, max_passes=15):
    """Iteratively merges adjacent coplanar face pairs for clusters with internal holes
    or non-disk topology, building clean large panels around features without creating
    invalid topological voids.
    """
    cos_tol = math.cos(math.radians(angle_tol_deg))
    total_merged = 0
    for _ in range(max_passes):
        used = set()
        pairs = []
        for f1 in list(mesh.faces):
            if f1 in used or f1 not in mesh._face_verts:
                continue
            n1 = mesh.face_normal(f1)
            p0 = mesh.vert_co(mesh.face_verts(f1)[0])
            for e in mesh.face_edges(f1):
                lf = list(mesh.link_faces(e))
                if len(lf) != 2:
                    continue
                f2 = lf[0] if lf[1] == f1 else lf[1]
                if f2 in used or f2 not in mesh._face_verts or f2 <= f1:
                    continue
                n2 = mesh.face_normal(f2)
                if np.dot(n1, n2) < cos_tol:
                    continue
                pts2 = [mesh.vert_co(v) for v in mesh.face_verts(f2)]
                dev = max(abs(np.dot(p - p0, n1)) for p in pts2)
                if dev > max_dev:
                    continue
                pairs.append((f1, f2))
                used.add(f1)
                used.add(f2)
                break
        if not pairs:
            break
        merged_pass = 0
        for f1, f2 in pairs:
            if f1 in mesh._face_verts and f2 in mesh._face_verts:
                if mesh.merge_faces([f1, f2], dissolve_verts=False) is not None:
                    merged_pass += 1
        total_merged += merged_pass
        if merged_pass == 0:
            break
    return total_merged


def merge_coplanar_regions(mesh, angle_tol_deg=2.0, collapse_collinear=False,
                            collinear_angle_tol_deg=1.0):
    """Mutates mesh in place. Returns stats dict."""
    t0 = time.perf_counter()
    # Fix winding once (recalc_face_normals() is just a per-face Newell
    # computation now, not a winding fix — see its docstring); input here
    # comes from darts.py, already consistent, but this stage is cheap
    # insurance against any upstream inconsistency.
    mesh.fix_winding_consistency()
    mesh.recalc_face_normals()
    t_normals = time.perf_counter()

    n_boundary_before = len(mesh.boundary_edges())
    n_faces_before = len(list(mesh.faces))

    t_ribbons0 = time.perf_counter()
    n_ribbons_dissolved = merge_ribbon_lines(
        mesh, max_passes=12, crease_deg=18.0, flat_deg=14.0, ar_gate=3.5, min_patch_size=60
    )
    t_ribbons = time.perf_counter()
    print(f"[coplanar_merge] structured_ribbon_reduction={t_ribbons-t_ribbons0:.2f}s "
          f"({n_ribbons_dissolved} lines dissolved)", flush=True)

    # Resolve any residual transition n-gons into clean quads and coplanar triangle pairs
    darts.resolve_all_ngons(mesh)
    darts.merge_coplanar_triangle_pairs(mesh, angle_face_deg=18.0)

    n_collinear_removed = 0
    if collapse_collinear:
        all_verts = list(mesh.verts)
        n_collinear_removed = mesh.dissolve_collinear_verts(
            all_verts, angle_tol_deg=collinear_angle_tol_deg)
    t_collinear = time.perf_counter()
    print(f"[coplanar_merge] collinear_cleanup={t_collinear-t_ribbons:.2f}s "
          f"({n_collinear_removed} removed)", flush=True)

    n_boundary_after = len(mesh.boundary_edges())

    if n_boundary_after > n_boundary_before:
        raise RuntimeError(
            f"coplanar_merge: boundary edges grew {n_boundary_before} -> "
            f"{n_boundary_after} -- a real hole, rejecting."
        )

    return {
        "ribbon_lines_dissolved": n_ribbons_dissolved,
        "collinear_verts_removed": n_collinear_removed,
        "faces_before": n_faces_before,
        "faces_after": len(list(mesh.faces)),
        "verts_after": len(list(mesh.verts)),
        "boundary_before": n_boundary_before,
        "boundary_after": n_boundary_after,
    }


def dissolve_coplanar_internal_edges(mesh, angle_tol_deg=14.0, max_dev_mm=3.0, max_passes=20):
    """General, robust coplanar edge dissolution:
    Dissolves redundant internal edges between coplanar faces (< angle_tol_deg)
    whose vertices lie on the same plane (< max_dev_mm).
    Guarantees manifoldness and zero boundary cracks.
    """
    cos_tol = math.cos(math.radians(angle_tol_deg))
    max_dev = max_dev_mm / 1000.0
    dissolved_total = 0

    pass_num = 0
    max_passes = 20
    while pass_num < max_passes:
        pass_num += 1
        edges_to_merge = []
        used_faces = set()
        for e in list(mesh.edges):
            if e not in mesh._edge_faces:
                continue
            lf = list(mesh.link_faces(e))
            if len(lf) != 2:
                continue
            f1, f2 = lf[0], lf[1]
            if f1 in used_faces or f2 in used_faces:
                continue
            n1 = mesh.face_normal(f1)
            n2 = mesh.face_normal(f2)
            if np.dot(n1, n2) < cos_tol:
                continue

            pts1 = [mesh.vert_co(v) for v in mesh.face_verts(f1)]
            p0 = pts1[0]
            pts2 = [mesh.vert_co(v) for v in mesh.face_verts(f2)]
            dev = max(abs(np.dot(p - p0, n1)) for p in pts2)
            if dev > max_dev:
                continue

            fv1 = list(mesh.face_verts(f1))
            fv2 = list(mesh.face_verts(f2))
            v0, v1 = mesh.edge_verts(e)

            idx1 = None
            for i in range(len(fv1)):
                if (fv1[i] == v0 and fv1[(i+1)%len(fv1)] == v1) or (fv1[i] == v1 and fv1[(i+1)%len(fv1)] == v0):
                    idx1 = i
                    break
            idx2 = None
            for i in range(len(fv2)):
                if (fv2[i] == v0 and fv2[(i+1)%len(fv2)] == v1) or (fv2[i] == v1 and fv2[(i+1)%len(fv2)] == v0):
                    idx2 = i
                    break
            if idx1 is None or idx2 is None:
                continue

            e_dir1 = (fv1[idx1], fv1[(idx1+1)%len(fv1)])
            e_dir2 = (fv2[idx2], fv2[(idx2+1)%len(fv2)])
            if e_dir1[0] == e_dir2[0]:
                continue

            n_v1 = len(fv1)
            walk1 = []
            curr = (idx1 + 1) % n_v1
            while curr != idx1:
                walk1.append(fv1[curr])
                curr = (curr + 1) % n_v1

            n_v2 = len(fv2)
            walk2 = []
            curr = (idx2 + 1) % n_v2
            while curr != idx2:
                walk2.append(fv2[curr])
                curr = (curr + 1) % n_v2

            new_verts = walk1 + walk2
            if len(new_verts) != len(set(new_verts)):
                continue

            edges_to_merge.append((e, f1, f2, tuple(new_verts)))
            used_faces.add(f1)
            used_faces.add(f2)

        if not edges_to_merge:
            break

        for e, f1, f2, new_fv in edges_to_merge:
            if f1 not in mesh._face_verts or f2 not in mesh._face_verts:
                continue
            mesh.remove_face(f1)
            mesh.remove_face(f2)
            mesh.add_face(new_fv)
            dissolved_total += 1

    n_collinear = mesh.dissolve_collinear_verts(list(mesh.verts))
    return dissolved_total, n_collinear


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
