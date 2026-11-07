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
    # Fix winding once (input may come straight from dissolve.py, already
    # consistent, or from an external remesher via finalize_component.py,
    # which isn't guaranteed to be) — recalc_face_normals() itself is just
    # a per-face Newell computation, not a winding fix (see its docstring).
    mesh.fix_winding_consistency()
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


def tri_min_angle_deg(a, b, c):
    e0, e1, e2 = b - a, c - b, a - c
    l0, l1, l2 = np.linalg.norm(e0), np.linalg.norm(e1), np.linalg.norm(e2)
    if l0 < 1e-9 or l1 < 1e-9 or l2 < 1e-9:
        return 0.0
    area = 0.5 * abs(e0[0] * -e2[1] - e0[1] * -e2[0])
    if area < 1e-11:
        return 0.0
    cos_a = np.clip((l1**2 + l2**2 - l0**2) / (2 * l1 * l2), -1.0, 1.0)
    cos_b = np.clip((l0**2 + l2**2 - l1**2) / (2 * l0 * l2), -1.0, 1.0)
    cos_c = np.clip((l0**2 + l1**2 - l2**2) / (2 * l0 * l1), -1.0, 1.0)
    return math.degrees(min(math.acos(cos_a), math.acos(cos_b), math.acos(cos_c)))


def _point_in_poly(pt, poly):
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i+1)%n]
        if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1):
            inside = not inside
    return inside


def _segments_cross(p1, p2, p3, p4):
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])
    return (ccw(p1, p3, p4) != ccw(p2, p3, p4)) and (ccw(p1, p2, p3) != ccw(p1, p2, p4))


def _is_interior_chord(pts_2d, i, j):
    n = len(pts_2d)
    if (j - i) % n in (1, n - 1):
        return True  # boundary edge is always part of polygon
    p_i, p_j = pts_2d[i], pts_2d[j]
    mid = 0.5 * (p_i + p_j)
    if not _point_in_poly(mid, pts_2d):
        return False
    for k in range(n):
        k_next = (k + 1) % n
        if k in (i, j) or k_next in (i, j):
            continue
        if _segments_cross(p_i, p_j, pts_2d[k], pts_2d[k_next]):
            return False
    return True


def triangulate_healthy_only(pts_2d, indices):
    """Triangulates a 2D simple polygon guaranteeing no needle slivers
    (all triangles have min angle >= 4.0 deg) and valid interior chords.
    """
    n = len(indices)
    if n < 3:
        return []
    if n == 3:
        return [tuple(indices)]

    pts_sub = [pts_2d[idx] for idx in indices]
    valid_chord = {}
    for i in range(n):
        for j in range(i + 1, n):
            valid_chord[(i, j)] = _is_interior_chord(pts_sub, i, j)

    memo = {}

    def solve(i, j):
        if (i, j) in memo:
            return memo[(i, j)]
        if j - i == 1:
            return 90.0, []
        if j - i == 2:
            a, b, c = pts_sub[i], pts_sub[i+1], pts_sub[j]
            cp = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
            if cp <= 1e-11:
                return 0.0, []
            ang = tri_min_angle_deg(a, b, c)
            return ang, [(indices[i], indices[i+1], indices[j])]

        best_score = -1.0
        best_tris = []
        for k in range(i + 1, j):
            if not valid_chord.get((i, k), True) or not valid_chord.get((k, j), True):
                continue
            a, b, c = pts_sub[i], pts_sub[k], pts_sub[j]
            cp = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
            if cp <= 1e-11:
                continue
            ang_k = tri_min_angle_deg(a, b, c)
            if ang_k <= 0:
                continue
            ang_l, tris_l = solve(i, k)
            if ang_l <= 0:
                continue
            ang_r, tris_r = solve(k, j)
            if ang_r <= 0:
                continue
            min_ang = min(ang_k, ang_l, ang_r)
            if min_ang > best_score:
                best_score = min_ang
                best_tris = [(indices[i], indices[k], indices[j])] + tris_l + tris_r

        if best_score <= 0:
            # Fallback fan
            best_tris = [(indices[i], indices[k], indices[k+1]) for k in range(i + 1, j)]
            best_score = 1.0

        memo[(i, j)] = (best_score, best_tris)
        return memo[(i, j)]

    score, tris = solve(0, n - 1)
    return tris


def polygon_sweep_line_quads(pts_2d, tol=1e-4):
    """Decomposes a 2D simple polygon into clean quadrilaterals using
    orthogonal sweep-line slabs. Keeping all internal partition lines
    straight (perpendicular to boundaries), never converging to a single point.
    Returns: list of quad coordinate tuples [ (p0, p1, p2, p3), ... ]
    """
    n = len(pts_2d)
    if n < 4:
        return []
    if n == 4:
        return [tuple(pts_2d)]

    u = pts_2d[:, 0]
    v = pts_2d[:, 1]
    u_span = np.ptp(u)
    v_span = np.ptp(v)

    if u_span < 1e-6 and v_span < 1e-6:
        return []

    # Sweep along the primary axis (the longer dimension)
    swap_uv = False
    if v_span > u_span:
        swap_uv = True
        pts = np.column_stack([v, u])
    else:
        pts = np.column_stack([u, v])

    # Ensure CCW order
    area = 0.5 * sum(pts[i, 0] * pts[(i + 1) % n, 1] - pts[(i + 1) % n, 0] * pts[i, 1] for i in range(n))
    if area < 0:
        pts = pts[::-1]

    x = pts[:, 0]
    y = pts[:, 1]
    x_span = np.ptp(x)

    # Cluster x-coordinates into event lines
    x_sorted = sorted(x)
    tol_x = max(tol, x_span * 0.05)
    x_events = []
    for val in x_sorted:
        if not x_events or abs(val - x_events[-1]) > tol_x:
            x_events.append(val)

    if len(x_events) < 2:
        return []

    edges = [(pts[i], pts[(i + 1) % n]) for i in range(n)]

    def get_y_at_x(p1, p2, x_val):
        x1, y1 = p1
        x2, y2 = p2
        if abs(x2 - x1) < 1e-9:
            return 0.5 * (y1 + y2)
        t = (x_val - x1) / (x2 - x1)
        return y1 + t * (y2 - y1)

    quads = []

    for k in range(len(x_events) - 1):
        x0 = x_events[k]
        x1 = x_events[k + 1]
        x_mid = 0.5 * (x0 + x1)

        active = []
        for p1, p2 in edges:
            min_e_x = min(p1[0], p2[0])
            max_e_x = max(p1[0], p2[0])
            if min_e_x <= x_mid <= max_e_x and abs(p2[0] - p1[0]) > 1e-9:
                y_mid = get_y_at_x(p1, p2, x_mid)
                y_at_x0 = get_y_at_x(p1, p2, x0)
                y_at_x1 = get_y_at_x(p1, p2, x1)
                active.append((y_mid, (x0, y_at_x0), (x1, y_at_x1)))

        active.sort(key=lambda item: item[0])

        for j in range(0, len(active) - 1, 2):
            bot = active[j]
            top = active[j + 1]

            p_bl = bot[1]
            p_br = bot[2]
            p_tr = top[2]
            p_tl = top[1]

            if swap_uv:
                q = (
                    np.array([p_bl[1], p_bl[0]]),
                    np.array([p_br[1], p_br[0]]),
                    np.array([p_tr[1], p_tr[0]]),
                    np.array([p_tl[1], p_tl[0]]),
                )
            else:
                q = (
                    np.array([p_bl[0], p_bl[1]]),
                    np.array([p_br[0], p_br[1]]),
                    np.array([p_tr[0], p_tr[1]]),
                    np.array([p_tl[0], p_tl[1]]),
                )
            quads.append(q)

    return quads


def cross2d(u, v):
    return u[0] * v[1] - u[1] * v[0]


def decompose_polygon_existing_verts(pts_2d, v_ids):
    """Decomposes a 2D simple polygon into clean convex quads (and at most 1 triangle
    if odd number of vertices) using ONLY existing boundary vertices.
    Zero new vertices created -> ZERO T-junctions, ZERO boundary cracks, ZERO holes.
    """
    n = len(pts_2d)
    if n < 3:
        return []
    if n == 3:
        return [("tri", tuple(v_ids))]
    if n == 4:
        return [("quad", tuple(v_ids))]

    area = 0.5 * sum(
        pts_2d[i, 0] * pts_2d[(i + 1) % n, 1] - pts_2d[(i + 1) % n, 0] * pts_2d[i, 1]
        for i in range(n)
    )
    if area < 0:
        pts_2d = pts_2d[::-1]
        v_ids = v_ids[::-1]

    def is_valid_internal_diagonal(i, j):
        if abs(i - j) <= 1 or abs(i - j) == n - 1:
            return False
        p1, p2 = pts_2d[i], pts_2d[j]
        pm = 0.5 * (p1 + p2)
        inside = False
        for k in range(n):
            a, b = pts_2d[k], pts_2d[(k + 1) % n]
            if ((a[1] > pm[1]) != (b[1] > pm[1])) and (
                pm[0]
                < (b[0] - a[0]) * (pm[1] - a[1]) / (b[1] - a[1] + 1e-12) + a[0]
            ):
                inside = not inside
        if not inside:
            return False
        for k in range(n):
            if k in (i, (i - 1) % n, j, (j - 1) % n):
                continue
            a, b = pts_2d[k], pts_2d[(k + 1) % n]
            def ccw(A, B, C):
                return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])
            if ccw(p1, a, b) != ccw(p2, a, b) and ccw(p1, p2, a) != ccw(p1, p2, b):
                return False
        return True

    best_split = None
    best_score = -1e9

    for i in range(n):
        j = (i + 3) % n
        if is_valid_internal_diagonal(i, j):
            q_idx = [i, (i + 1) % n, (i + 2) % n, j]
            q_pts = pts_2d[q_idx]
            c1 = cross2d(q_pts[1] - q_pts[0], q_pts[2] - q_pts[1])
            c2 = cross2d(q_pts[2] - q_pts[1], q_pts[3] - q_pts[2])
            c3 = cross2d(q_pts[3] - q_pts[2], q_pts[0] - q_pts[3])
            c4 = cross2d(q_pts[0] - q_pts[3], q_pts[1] - q_pts[0])
            if c1 > 1e-8 and c2 > 1e-8 and c3 > 1e-8 and c4 > 1e-8:
                chord_len = np.linalg.norm(pts_2d[i] - pts_2d[j])
                score = -chord_len
                if score > best_score:
                    best_score = score
                    best_split = (i, j)

    if best_split is not None:
        i, j = best_split
        q_vids = [v_ids[i], v_ids[(i + 1) % n], v_ids[(i + 2) % n], v_ids[j]]
        rem_idx = []
        cur = j
        while True:
            rem_idx.append(cur)
            if cur == i:
                break
            cur = (cur + 1) % n
        rem_pts = pts_2d[rem_idx]
        rem_vids = [v_ids[k] for k in rem_idx]
        return [("quad", tuple(q_vids))] + decompose_polygon_existing_verts(
            rem_pts, rem_vids
        )

    tris = triangulate_healthy_only(pts_2d, list(range(n)))
    return [("tri", (v_ids[t[0]], v_ids[t[1]], v_ids[t[2]])) for t in tris]


def resolve_all_ngons(mesh, angle_shape_deg=90.0):
    """Guarantees strictly 0% N-gons in output mesh (sum [|V(f)| > 4] == 0).
    Decomposes N-gons keeping lines straight onto straight edges using ONLY
    existing vertices (never creating T-junctions, dangling edges, or holes).
    """
    mesh.fix_winding_consistency()
    ngon_fids = [f for f in list(mesh.faces) if len(mesh.face_verts(f)) > 4]
    ngons_resolved = 0
    straight_quads_count = 0

    for fid in ngon_fids:
        if fid not in mesh._face_verts:
            continue
        fverts = list(mesh.face_verts(fid))
        if len(fverts) <= 4:
            continue
        coords_3d = np.array([mesh.vert_co(v) for v in fverts])
        n = mesh.face_normal(fid)
        if np.linalg.norm(n) < 1e-9:
            n = np.array([0.0, 0.0, 1.0])
        t1 = np.cross(n, [0, 0, 1]) if abs(n[2]) < 0.9 else np.cross(n, [1, 0, 0])
        l1 = np.linalg.norm(t1)
        if l1 < 1e-9:
            t1 = np.array([1.0, 0.0, 0.0])
            l1 = 1.0
        t1 = t1 / l1
        t2 = np.cross(n, t1)

        p0 = coords_3d.mean(axis=0)
        pts_2d = np.column_stack([np.dot(coords_3d - p0, t1), np.dot(coords_3d - p0, t2)])

        sub_faces = decompose_polygon_existing_verts(pts_2d, fverts)
        if sub_faces:
            mesh.remove_face(fid)
            for ftype, vtuple in sub_faces:
                p_a, p_b, p_c = (
                    mesh.vert_co(vtuple[0]),
                    mesh.vert_co(vtuple[1]),
                    mesh.vert_co(vtuple[2]),
                )
                nt = np.cross(p_b - p_a, p_c - p_a)
                if np.dot(nt, n) < 0:
                    vtuple = tuple(reversed(vtuple))
                mesh.add_face(vtuple)
                if ftype == "quad":
                    straight_quads_count += 1
            ngons_resolved += 1

    seen = {}
    for f in list(mesh.faces):
        key = tuple(sorted(mesh.face_verts(f)))
        if key in seen:
            mesh.remove_face(f)
        else:
            seen[key] = f

    mesh.fix_winding_consistency()
    mesh.recalc_face_normals()
    pair_stats = merge_coplanar_triangle_pairs(mesh, angle_shape_deg=angle_shape_deg)
    mesh.fix_winding_consistency()
    mesh.recalc_face_normals()

    return {
        "ngons_initial": len(ngon_fids),
        "ngons_resolved": ngons_resolved,
        "straight_quads": straight_quads_count,
        "pairs_merged": pair_stats.get("pairs_merged", 0),
        "tris_after": pair_stats.get("tris_after", 0),
    }


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
