"""
Self-contained extraction of the `coarsen_all_scales_ruler_straight` quad-mesh
coarsening algorithm and its full transitive dependency closure.

Source: "/Users/bhargavreddy/gemini_tripo pipeline/tripo_smart_mesh_retopo_pipeline 2/"
  (primarily test_with_3x2_strips.py, test_nondestructive_grower.py,
   test_whole_asset_coarsener.py, test_ruler_straight_everywhere.py,
   test_resampled_ubiquitous.py, test_subgrid_heap_coarsener.py,
   test_edge_guided_panel_coarsen.py, run_perfect_ubiquitous_all5.py,
   and tripo_anisotropic_pipeline.py)

Conventions (unchanged from the source codebase):
  - verts: an (N, 3) numpy array of float vertex positions.
  - faces: a list of int lists (each a quad [a,b,c,d] or triangle [a,b,c]),
    referencing row indices into `verts`.
  - kdtree: a scipy.spatial.cKDTree built over a dense point sample of the
    original ground-truth surface (`sub_pts`), used to query local surface
    deviation / crease information.
  - sub_pts / sub_nrms: (M, 3) arrays of ground-truth surface sample points
    and their normals, aligned with `kdtree`.
  - h_base: a characteristic edge-length / voxel-size scale used to turn the
    various ratio thresholds below into absolute distances.

Pure numpy/scipy logic only: no cv2, no matplotlib, no file I/O or GLB parsing.
"""

import heapq
from collections import defaultdict

import numpy as np


# ---------------------------------------------------------------------------
# Low-level geometric quality helpers
# ---------------------------------------------------------------------------

def face_min_ang_and_fold(pts_f):
    """
    Returns (min_corner_angle_deg, fold_cos) for a planar polygon's 3D corner
    points `pts_f` (k x 3 array, k=3 or 4):
      - min_corner_angle_deg: the smallest interior corner angle, in degrees.
      - fold_cos: for a quad, the cosine of the angle between its two
        triangle-fan normals (1.0 = perfectly flat, <0 = folded/self-intersecting);
        for a triangle, always 1.0.
    Returns (-1.0, -1.0) if the polygon is degenerate (near-zero edge length,
    extreme aspect ratio, non-convex corner, or a folded quad).
    """
    k = len(pts_f)
    edges = [pts_f[(i + 1) % k] - pts_f[i] for i in range(k)]
    lens = [np.linalg.norm(e) for e in edges]
    if min(lens) < 1e-9 or max(lens) / min(lens) > 12.0:
        return -1.0, -1.0
    sins = [np.linalg.norm(np.cross(-edges[(i - 1) % k] / lens[(i - 1) % k], edges[i] / lens[i])) for i in range(k)]
    min_ang = np.degrees(np.arcsin(np.clip(min(sins), 0.0, 1.0)))
    n1 = np.cross(pts_f[1] - pts_f[0], pts_f[2] - pts_f[0])
    ln1 = np.linalg.norm(n1)
    if ln1 < 1e-11:
        return -1.0, -1.0
    if k == 4:
        n2 = np.cross(pts_f[2] - pts_f[0], pts_f[3] - pts_f[0])
        ln2 = np.linalg.norm(n2)
        if ln2 < 1e-11:
            return -1.0, -1.0
        nf = (n1 + n2) / (np.linalg.norm(n1 + n2) + 1e-12)
        for i in range(4):
            u = -edges[(i - 1) % 4] / lens[(i - 1) % 4]
            v = edges[i] / lens[i]
            if np.dot(np.cross(v, u), nf) <= 0.02:
                return -1.0, -1.0
        return min_ang, float(np.dot(n1 / ln1, n2 / ln2))
    return min_ang, 1.0


def emit_optimal_5gon_border(verts, A, M, B, C, D, orient_face):
    """
    Adaptively selects the highest-quality convex split of the 5-gon border interval (A, C, D, B, M):
      - Split A: Quad [A, C, D, M] + Tri [M, D, B]
      - Split B: Tri [A, C, M] + Quad [M, C, D, B]
      - Split C: 3 Tris [A, C, M], [M, C, D], [M, D, B] (fallback when curved/sheared)
    """
    qA, tA = orient_face([A, C, D, M]), orient_face([M, D, B])
    tB, qB = orient_face([A, C, M]), orient_face([M, C, D, B])
    ang_qA, fold_qA = face_min_ang_and_fold(verts[qA])
    ang_tA, _       = face_min_ang_and_fold(verts[tA])
    ang_qB, fold_qB = face_min_ang_and_fold(verts[qB])
    ang_tB, _       = face_min_ang_and_fold(verts[tB])

    scoreA = min(ang_qA, ang_tA) if (fold_qA >= 0.65 and min(ang_qA, ang_tA) >= 10.0) else -1.0
    scoreB = min(ang_qB, ang_tB) if (fold_qB >= 0.65 and min(ang_qB, ang_tB) >= 10.0) else -1.0

    if scoreA >= scoreB and scoreA > 0:
        return [qA, tA]
    elif scoreB > 0:
        return [tB, qB]
    else:
        return [orient_face([A, C, M]), orient_face([M, C, D]), orient_face([M, D, B])]


def remove_valence2_doublets(verts, faces):
    """
    Repeatedly removes valence-2 "doublet" vertices (vertices shared by exactly
    two faces and with exactly two edge-neighbors) by splicing them out of
    both incident faces, then compacts the vertex array. Used as cleanup after
    diagonal-collapse style topology edits that can leave such doublets behind.
    """
    verts = verts.copy()
    faces = [list(f) for f in faces if len(set(f)) == len(f) and len(f) >= 3]
    for _ in range(4):
        vf = defaultdict(list)
        vert_adj = defaultdict(set)
        for fi, f in enumerate(faces):
            k = len(f)
            for i in range(k):
                u, v = f[i], f[(i + 1) % k]
                vf[u].append(fi)
                vert_adj[u].add(v); vert_adj[v].add(u)
        v2_list = [v for v, nbs in vert_adj.items() if len(nbs) == 2 and len(vf[v]) == 2]
        if not v2_list:
            break
        locked_f = set()
        for v in v2_list:
            f1_i, f2_i = vf[v]
            if f1_i in locked_f or f2_i in locked_f:
                continue
            for fi in (f1_i, f2_i):
                f_old = faces[fi]
                f_new = [x for x in f_old if x != v]
                faces[fi] = f_new if len(set(f_new)) >= 3 else []
                locked_f.add(fi)
        faces = [f for f in faces if len(f) >= 3]
    used_v = sorted(set(v for f in faces for v in f))
    remap = {old_v: new_i for new_i, old_v in enumerate(used_v)}
    return verts[used_v], [[remap[v] for v in f] for f in faces]


# ---------------------------------------------------------------------------
# Optional pre-pass: collapse Dual-Contouring staircase step-quads
# ---------------------------------------------------------------------------

def unkinked_step_quad_regularizer(verts, faces, kdtree, h_base, max_dev_ratio=0.26, passes=10):
    """
    Collapses (3, 5, 3, 5) Dual Contouring staircase step-quads along their short diagonal
    whenever the midpoint lies within `max_dev_ratio * h_base` of the raw .glb surface and all
    resulting quads remain strictly convex (fold >= 0.55).
    Unlike a dihedral-crease-angle based detector, this never mistakes a 60-90 deg Dual Contouring
    voxel staircase step on a thin fin or mecha wing for a sharp crease!
    """
    verts = verts.copy()
    faces = [list(f) for f in faces if len(f) >= 3]
    max_dev = max_dev_ratio * h_base

    for _ in range(passes):
        vert_val = defaultdict(set)
        vf_map = defaultdict(list)
        for fi, f in enumerate(faces):
            for k in range(len(f)):
                a, b = f[k], f[(k + 1) % len(f)]
                vert_val[a].add(b); vert_val[b].add(a)
                vf_map[a].append(fi)
        val = {v: len(nbs) for v, nbs in vert_val.items()}

        locked_v = set()
        diag_collapses = 0
        for fi, f in enumerate(faces):
            if len(f) != 4 or any(v in locked_v for v in f):
                continue
            v0, v1, v2, v3 = f
            err_before = sum((val.get(v, 4) - 4) ** 2 for v in (v0, v1, v2, v3))
            err_02 = (val.get(v0, 4) + val.get(v2, 4) - 6) ** 2 + (val.get(v1, 4) - 5) ** 2 + (val.get(v3, 4) - 5) ** 2
            err_13 = (val.get(v1, 4) + val.get(v3, 4) - 6) ** 2 + (val.get(v0, 4) - 5) ** 2 + (val.get(v2, 4) - 5) ** 2
            d02 = np.linalg.norm(verts[v0] - verts[v2])
            d13 = np.linalg.norm(verts[v1] - verts[v3])
            cand_02 = (err_02 < err_before and val.get(v1, 4) >= 4 and val.get(v3, 4) >= 4 and d02 <= 1.25 * h_base)
            cand_13 = (err_13 < err_before and val.get(v0, 4) >= 4 and val.get(v2, 4) >= 4 and d13 <= 1.25 * h_base)

            target_pair = other_pair = None
            if cand_02 and (not cand_13 or err_02 < err_13 or (err_02 == err_13 and d02 <= d13)):
                target_pair, other_pair = (v0, v2), (v1, v3)
            elif cand_13:
                target_pair, other_pair = (v1, v3), (v0, v2)

            if target_pair is not None:
                u, v = target_pair
                w1, w2 = other_pair
                if vert_val[u].intersection(vert_val[v]) != {w1, w2}:
                    continue
                if any(nb in locked_v for nb in (vert_val[u] | vert_val[v])):
                    continue
                mid = 0.5 * (verts[u] + verts[v])
                d_mid, _ = kdtree.query(mid, k=1)
                if d_mid > max_dev:
                    continue
                inc_f = set(vf_map[u] + vf_map[v]) - {fi}
                if not all(len(set(u if x == v else x for x in faces[iff])) == len(faces[iff]) for iff in inc_f):
                    continue

                old_u, old_v = verts[u].copy(), verts[v].copy()
                verts[u] = mid
                verts[v] = mid
                if not all(face_min_ang_and_fold(verts[[u if x == v else x for x in faces[iff]]])[1] >= 0.55 for iff in inc_f):
                    verts[u], verts[v] = old_u, old_v
                    continue

                faces[fi] = []
                for iff in inc_f:
                    faces[iff] = [u if x == v else x for x in faces[iff]]
                locked_v.update(vert_val[u] | vert_val[v] | {u, v})
                diag_collapses += 1

        faces = [f for f in faces if len(f) > 0]
        verts, faces = remove_valence2_doublets(verts, faces)
        if diag_collapses == 0:
            break

    used_v = sorted(set(v for f in faces for v in f))
    remap = {old_v: new_i for new_i, old_v in enumerate(used_v)}
    return verts[used_v], [[remap[v] for v in f] for f in faces]


# ---------------------------------------------------------------------------
# Ruler-straight coarse-grid index computation & interior re-positioning
# ---------------------------------------------------------------------------

def compute_ruler_straight_indices(R, C, sr, sc):
    """
    Computes strictly interior coarse grid indices (r_idx, c_idx) inside [1..R-1] x [1..C-1]
    so 100% of interior coarse quad vertices are strictly interior to the patch (never pinched
    into trapezoids by outer perimeter vertices!).
    Supports:
    - Any 2D multi-quad grid with nr * nc >= 2 (including 4x4, 5x4, 4x5, 5x5, 5x3, 3x5, 6x3, 3x6)
    - 4x3 (r_idx=[1, 3], c_idx=[1, 2]) and 3x4 (r_idx=[1, 2], c_idx=[1, 3]), where the span=1
      axis has ZERO triangles on its two borders (forming a 3-quad stacked column with only 2 side triangles!),
      while still banning 4x4 (r_idx=[1, 3], c_idx=[1, 3]) 4-sided single-quad triangle bullseyes!
    """
    if R < 3 or C < 3 or (R == 3 and C == 3):
        return None, None

    if sr == 1:
        r_idx = list(range(1, R))
    else:
        r_idx = list(range(1, R - 1, sr))
        if not r_idx or r_idx[-1] != R - 1:
            if r_idx and (R - 1) - r_idx[-1] == 1 and len(r_idx) >= 3:
                r_idx[-1] = R - 1
            else:
                r_idx.append(R - 1)
        r_idx = sorted(set([1] + r_idx + [R - 1]))

    if sc == 1:
        c_idx = list(range(1, C))
    else:
        c_idx = list(range(1, C - 1, sc))
        if not c_idx or c_idx[-1] != C - 1:
            if c_idx and (C - 1) - c_idx[-1] == 1 and len(c_idx) >= 3:
                c_idx[-1] = C - 1
            else:
                c_idx.append(C - 1)
        c_idx = sorted(set([1] + c_idx + [C - 1]))

    nr = len(r_idx) - 1
    nc = len(c_idx) - 1
    if nr < 1 or nc < 1:
        return None, None
    if nr == R - 2 and nc == C - 2:
        return None, None

    # Ban 4-sided single-quad bullseyes (where nr==1 and nc==1 and BOTH R>=4 and C>=4 have span>=2 borders on all 4 sides!)
    if nr * nc == 1:
        # Allowed ONLY on 4x3 (where C==3 has span=1 pure-quad top/bottom borders) or 3x4 (where R==3 has span=1 pure-quad left/right borders)!
        if not ((R == 4 and C == 3) or (R == 3 and C == 4)):
            return None, None

    return r_idx, c_idx


def ruler_straight_interior_positions(verts, R, C, V_grid, r_idx, c_idx):
    """
    Bilinearly resamples the positions of every interior coarse grid vertex
    (r_i, c_j) for r_i in r_idx, c_j in c_idx, so that interior coarse quads
    stay evenly ("ruler-straight") spaced across [margin, R - margin] x
    [margin, C - margin] on the fine quad grid V_grid.
    """
    nr = len(r_idx) - 1
    nc = len(c_idx) - 1
    r_margin = 0.78 if R == 3 else (0.86 if R == 4 and nr >= 2 else 1.0)
    c_margin = 0.78 if C == 3 else (0.86 if C == 4 and nc >= 2 else 1.0)
    u_targets = np.linspace(r_margin, R - r_margin, nr + 1)
    v_targets = np.linspace(c_margin, C - c_margin, nc + 1)
    new_pos = {}
    for ir, r_i in enumerate(r_idx):
        u = u_targets[ir]
        ru = min(max(int(np.floor(u)), 0), R - 1)
        du = u - ru
        for ic, c_j in enumerate(c_idx):
            v = v_targets[ic]
            if abs(u - r_i) < 1e-6 and abs(v - c_j) < 1e-6:
                continue
            cv = min(max(int(np.floor(v)), 0), C - 1)
            dv = v - cv
            p_uv = (
                (1.0 - du) * (1.0 - dv) * verts[V_grid[ru][cv]]
                + du * (1.0 - dv) * verts[V_grid[ru + 1][cv]]
                + (1.0 - du) * dv * verts[V_grid[ru][cv + 1]]
                + du * dv * verts[V_grid[ru + 1][cv + 1]]
            )
            new_pos[V_grid[r_i][c_j]] = p_uv
    return new_pos


def build_patch_faces_from_indices(verts, R, C, V_grid, r_idx, c_idx, orient_face):
    """
    Builds the full set of coarse + border faces for an (R x C) patch given
    ruler-straight interior coarse-grid indices (r_idx, c_idx): interior coarse
    quads, 4 corner quads, and left/right/top/bottom border strips (which fan
    out as triangles, optimal 5-gon splits, or single quads depending on span).
    """
    new_patch_faces = []
    # 1. Interior coarse quads
    for ir in range(len(r_idx) - 1):
        ra, rb = r_idx[ir], r_idx[ir + 1]
        for ic in range(len(c_idx) - 1):
            ca, cb = c_idx[ic], c_idx[ic + 1]
            new_patch_faces.append(orient_face([V_grid[ra][ca], V_grid[rb][ca], V_grid[rb][cb], V_grid[ra][cb]]))

    # 2. Four corner quads
    new_patch_faces.append(orient_face([V_grid[0][0], V_grid[1][0], V_grid[1][1], V_grid[0][1]]))
    new_patch_faces.append(orient_face([V_grid[R - 1][0], V_grid[R][0], V_grid[R][1], V_grid[R - 1][1]]))
    new_patch_faces.append(orient_face([V_grid[0][C - 1], V_grid[1][C - 1], V_grid[1][C], V_grid[0][C]]))
    new_patch_faces.append(orient_face([V_grid[R - 1][C - 1], V_grid[R][C - 1], V_grid[R][C], V_grid[R - 1][C]]))

    # 3. Left & Right border strips
    for ir in range(len(r_idx) - 1):
        ra, rb = r_idx[ir], r_idx[ir + 1]
        span = rb - ra
        if span == 1:
            new_patch_faces.append(orient_face([V_grid[ra][0], V_grid[rb][0], V_grid[rb][1], V_grid[ra][1]]))
            new_patch_faces.append(orient_face([V_grid[ra][C - 1], V_grid[rb][C - 1], V_grid[rb][C], V_grid[ra][C]]))
        elif span == 2:
            m = ra + 1
            new_patch_faces.extend(emit_optimal_5gon_border(verts, V_grid[rb][0], V_grid[m][0], V_grid[ra][0], V_grid[rb][1], V_grid[ra][1], orient_face))
            new_patch_faces.extend(emit_optimal_5gon_border(verts, V_grid[ra][C], V_grid[m][C], V_grid[rb][C], V_grid[ra][C - 1], V_grid[rb][C - 1], orient_face))
        elif span % 2 == 1:
            m = (ra + rb) // 2
            for r in range(ra, m):
                new_patch_faces.append(orient_face([V_grid[r][0], V_grid[r + 1][0], V_grid[ra][1]]))
                new_patch_faces.append(orient_face([V_grid[ra][C - 1], V_grid[r + 1][C], V_grid[r][C]]))
            qL = orient_face([V_grid[m][0], V_grid[m + 1][0], V_grid[rb][1], V_grid[ra][1]])
            if face_min_ang_and_fold(verts[qL])[1] >= 0.60:
                new_patch_faces.append(qL)
            else:
                new_patch_faces.append(orient_face([V_grid[m][0], V_grid[m + 1][0], V_grid[ra][1]]))
                new_patch_faces.append(orient_face([V_grid[m + 1][0], V_grid[rb][1], V_grid[ra][1]]))
            qR = orient_face([V_grid[ra][C - 1], V_grid[rb][C - 1], V_grid[m + 1][C], V_grid[m][C]])
            if face_min_ang_and_fold(verts[qR])[1] >= 0.60:
                new_patch_faces.append(qR)
            else:
                new_patch_faces.append(orient_face([V_grid[ra][C - 1], V_grid[rb][C - 1], V_grid[m][C]]))
                new_patch_faces.append(orient_face([V_grid[rb][C - 1], V_grid[m + 1][C], V_grid[m][C]]))
            for r in range(m + 1, rb):
                new_patch_faces.append(orient_face([V_grid[r][0], V_grid[r + 1][0], V_grid[rb][1]]))
                new_patch_faces.append(orient_face([V_grid[rb][C - 1], V_grid[r + 1][C], V_grid[r][C]]))
        else:
            m = (ra + rb) // 2
            for r in range(ra, m):
                new_patch_faces.append(orient_face([V_grid[r][0], V_grid[r + 1][0], V_grid[ra][1]]))
                new_patch_faces.append(orient_face([V_grid[ra][C - 1], V_grid[r + 1][C], V_grid[r][C]]))
            new_patch_faces.append(orient_face([V_grid[m][0], V_grid[rb][1], V_grid[ra][1]]))
            new_patch_faces.append(orient_face([V_grid[ra][C - 1], V_grid[rb][C - 1], V_grid[m][C]]))
            for r in range(m, rb):
                new_patch_faces.append(orient_face([V_grid[r][0], V_grid[r + 1][0], V_grid[rb][1]]))
                new_patch_faces.append(orient_face([V_grid[rb][C - 1], V_grid[r + 1][C], V_grid[r][C]]))

    # 4. Top & Bottom border strips
    for ic in range(len(c_idx) - 1):
        ca, cb = c_idx[ic], c_idx[ic + 1]
        span = cb - ca
        if span == 1:
            new_patch_faces.append(orient_face([V_grid[0][ca], V_grid[1][ca], V_grid[1][cb], V_grid[0][cb]]))
            new_patch_faces.append(orient_face([V_grid[R - 1][ca], V_grid[R][ca], V_grid[R][cb], V_grid[R - 1][cb]]))
        elif span == 2:
            m = ca + 1
            new_patch_faces.extend(emit_optimal_5gon_border(verts, V_grid[0][ca], V_grid[0][m], V_grid[0][cb], V_grid[1][ca], V_grid[1][cb], orient_face))
            new_patch_faces.extend(emit_optimal_5gon_border(verts, V_grid[R][cb], V_grid[R][m], V_grid[R][ca], V_grid[R - 1][cb], V_grid[R - 1][ca], orient_face))
        elif span % 2 == 1:
            m = (ca + cb) // 2
            for c in range(ca, m):
                new_patch_faces.append(orient_face([V_grid[0][c], V_grid[1][ca], V_grid[0][c + 1]]))
                new_patch_faces.append(orient_face([V_grid[R - 1][ca], V_grid[R][c], V_grid[R][c + 1]]))
            qT = orient_face([V_grid[0][m], V_grid[1][ca], V_grid[1][cb], V_grid[0][m + 1]])
            if face_min_ang_and_fold(verts[qT])[1] >= 0.60:
                new_patch_faces.append(qT)
            else:
                new_patch_faces.append(orient_face([V_grid[0][m], V_grid[1][ca], V_grid[0][m + 1]]))
                new_patch_faces.append(orient_face([V_grid[0][m + 1], V_grid[1][ca], V_grid[1][cb]]))
            qB = orient_face([V_grid[R - 1][ca], V_grid[R][m], V_grid[R][m + 1], V_grid[R - 1][cb]])
            if face_min_ang_and_fold(verts[qB])[1] >= 0.60:
                new_patch_faces.append(qB)
            else:
                new_patch_faces.append(orient_face([V_grid[R - 1][ca], V_grid[R][m], V_grid[R][m + 1]]))
                new_patch_faces.append(orient_face([V_grid[R - 1][ca], V_grid[R][m + 1], V_grid[R - 1][cb]]))
            for c in range(m + 1, cb):
                new_patch_faces.append(orient_face([V_grid[0][c], V_grid[1][cb], V_grid[0][c + 1]]))
                new_patch_faces.append(orient_face([V_grid[R - 1][cb], V_grid[R][c], V_grid[R][c + 1]]))
        else:
            m = (ca + cb) // 2
            for c in range(ca, m):
                new_patch_faces.append(orient_face([V_grid[0][c], V_grid[1][ca], V_grid[0][c + 1]]))
                new_patch_faces.append(orient_face([V_grid[R - 1][ca], V_grid[R][c], V_grid[R][c + 1]]))
            new_patch_faces.append(orient_face([V_grid[0][m], V_grid[1][ca], V_grid[1][cb]]))
            new_patch_faces.append(orient_face([V_grid[R - 1][ca], V_grid[R][m], V_grid[R - 1][cb]]))
            for c in range(m, cb):
                new_patch_faces.append(orient_face([V_grid[0][c], V_grid[1][cb], V_grid[0][c + 1]]))
                new_patch_faces.append(orient_face([V_grid[R - 1][cb], V_grid[R][c], V_grid[R][c + 1]]))

    return new_patch_faces


def general_subblock_fidelity_gate(verts, R, C, Q_grid, V_grid, f_normals, r_idx, c_idx, cand_faces, max_chord_dist, min_normal_cos, max_ar=5.5):
    """
    Evaluates local chordal height & normal alignment for every coarse quad block [ra..rb, ca..cb]
    generated by r_idx and c_idx (supporting both 2D blocks and 1D full-width/full-height strips!),
    and verifies face convexity, corner angle >= 9.0 deg, and aspect ratio <= max_ar!
    """
    for ir in range(len(r_idx) - 1):
        ra, rb = r_idx[ir], r_idx[ir + 1]
        for ic in range(len(c_idx) - 1):
            ca, cb = c_idx[ic], c_idx[ic + 1]
            q_pts = verts[[V_grid[ra][ca], V_grid[rb][ca], V_grid[rb][cb], V_grid[ra][cb]]]
            n_q = np.cross(q_pts[1] - q_pts[0], q_pts[2] - q_pts[0]) + np.cross(q_pts[2] - q_pts[0], q_pts[3] - q_pts[0])
            ln = np.linalg.norm(n_q)
            if ln < 1e-11:
                return False
            n_q /= ln
            if np.dot(n_q, f_normals[Q_grid[ra][ca]]) < 0:
                n_q = -n_q
            c_q = q_pts.mean(axis=0)

            sub_v = [V_grid[r][c] for r in range(ra, rb + 1) for c in range(ca, cb + 1)]
            sub_pts_v = verts[sub_v]
            chord_err = np.max(np.abs((sub_pts_v - c_q) @ n_q))
            if chord_err > max_chord_dist:
                return False

            sub_f = [Q_grid[r][c] for r in range(ra, rb) for c in range(ca, cb)]
            if np.min(f_normals[sub_f] @ n_q) < min_normal_cos:
                return False

    min_sin = np.sin(np.radians(9.0))
    for nf_v in cand_faces:
        pts_f = verts[nf_v]
        k = len(pts_f)
        edges = [pts_f[(i + 1) % k] - pts_f[i] for i in range(k)]
        lens = [np.linalg.norm(e) for e in edges]
        if min(lens) < 1e-9 or max(lens) / min(lens) > max_ar:
            return False
        for i in range(k):
            u = -edges[(i - 1) % k] / lens[(i - 1) % k]
            v = edges[i] / lens[i]
            if np.linalg.norm(np.cross(u, v)) < min_sin:
                return False
        n = np.cross(pts_f[1] - pts_f[0], pts_f[2] - pts_f[0])
        ln = np.linalg.norm(n)
        if ln < 1e-11:
            return False
        if k == 4:
            n2 = np.cross(pts_f[2] - pts_f[0], pts_f[3] - pts_f[0])
            ln2 = np.linalg.norm(n2)
            if ln2 < 1e-11 or np.dot(n / ln, n2 / ln2) < 0.55:
                return False
    return True


def build_full_width_strip_faces(verts, R, C, V_grid, sc, orient_face):
    """
    Full-Width Strip Coarsening (sr = 1 along R, sc >= 2 across C):
    - NO left/right buffer columns needed because r_idx = [1, 2, ..., R-1] preserves every
      outer boundary edge along c = 0 and c = C 1-to-1!
    - Coarsens across C using c_idx = [0, sc, 2*sc, ..., C], emitting full-width coarse quads
      for rows r = 1 .. R-2, and adaptive 5-gon (1 Quad + 1 Tri) caps at r = 0..1 and r = R-1..R!
    """
    if R < 3 or C < 2:
        return None, None, None
    c_idx = list(range(0, C, sc))
    if c_idx[-1] != C:
        if C - c_idx[-1] == 1 and len(c_idx) > 1:
            c_idx[-1] = C
        else:
            c_idx.append(C)
    c_idx = sorted(set([0] + c_idx + [C]))
    if len(c_idx) - 1 >= C:
        return None, None, None

    r_idx = list(range(1, R))  # [1, 2, ..., R-1]
    if len(r_idx) < 2:
        return None, None, None

    new_faces = []
    # 1. Middle rows r = 1 .. R-2: 100% pure coarse quads spanning full width!
    for ir in range(len(r_idx) - 1):
        ra, rb = r_idx[ir], r_idx[ir + 1]  # rb = ra + 1
        for ic in range(len(c_idx) - 1):
            ca, cb = c_idx[ic], c_idx[ic + 1]
            new_faces.append(orient_face([V_grid[ra][ca], V_grid[rb][ca], V_grid[rb][cb], V_grid[ra][cb]]))

    # 2. Top cap (r = 0..1) and Bottom cap (r = R-1..R)
    for ic in range(len(c_idx) - 1):
        ca, cb = c_idx[ic], c_idx[ic + 1]
        span = cb - ca
        if span == 1:
            new_faces.append(orient_face([V_grid[0][ca], V_grid[1][ca], V_grid[1][cb], V_grid[0][cb]]))
            new_faces.append(orient_face([V_grid[R - 1][ca], V_grid[R][ca], V_grid[R][cb], V_grid[R - 1][cb]]))
        elif span == 2:
            m = ca + 1
            new_faces.extend(emit_optimal_5gon_border(verts, V_grid[0][ca], V_grid[0][m], V_grid[0][cb], V_grid[1][ca], V_grid[1][cb], orient_face))
            new_faces.extend(emit_optimal_5gon_border(verts, V_grid[R][cb], V_grid[R][m], V_grid[R][ca], V_grid[R - 1][cb], V_grid[R - 1][ca], orient_face))
        elif span == 3:
            m = ca + 1
            new_faces.append(orient_face([V_grid[0][ca], V_grid[1][ca], V_grid[0][m]]))
            qT = orient_face([V_grid[0][m], V_grid[1][ca], V_grid[1][cb], V_grid[0][m + 1]])
            if face_min_ang_and_fold(verts[qT])[1] >= 0.60:
                new_faces.append(qT)
            else:
                new_faces.append(orient_face([V_grid[0][m], V_grid[1][ca], V_grid[0][m + 1]]))
                new_faces.append(orient_face([V_grid[0][m + 1], V_grid[1][ca], V_grid[1][cb]]))
            new_faces.append(orient_face([V_grid[0][m + 1], V_grid[1][cb], V_grid[0][cb]]))

            new_faces.append(orient_face([V_grid[R - 1][ca], V_grid[R][ca], V_grid[R][m]]))
            qB = orient_face([V_grid[R - 1][ca], V_grid[R][m], V_grid[R][m + 1], V_grid[R - 1][cb]])
            if face_min_ang_and_fold(verts[qB])[1] >= 0.60:
                new_faces.append(qB)
            else:
                new_faces.append(orient_face([V_grid[R - 1][ca], V_grid[R][m], V_grid[R][m + 1]]))
                new_faces.append(orient_face([V_grid[R - 1][ca], V_grid[R][m + 1], V_grid[R - 1][cb]]))
            new_faces.append(orient_face([V_grid[R - 1][cb], V_grid[R][m + 1], V_grid[R][cb]]))
        else:
            return None, None, None

    return new_faces, r_idx, c_idx


# ---------------------------------------------------------------------------
# Rectangular sub-grid extraction & cropping around obstacles
# ---------------------------------------------------------------------------

def extract_subgrid(Q_grid, V_grid, r0, r1, c0, c1):
    Q_sub = [row[c0:c1] for row in Q_grid[r0:r1]]
    V_sub = [row[c0:c1 + 1] for row in V_grid[r0:r1 + 1]]
    return r1 - r0, c1 - c0, Q_sub, V_sub


def crop_to_free_subgrids(R, C, Q_grid, V_grid, used_f, interior_locked_v, all_patch_v, min_dim, min_area):
    """
    In O(R * C) array indexing, finds maximal collision-free sub-rectangles [r0:r1, c0:c1]
    inside (Q_grid, V_grid) where:
    - No face is in used_f
    - No vertex is in interior_locked_v
    - No strictly interior vertex (r0 < r < r1, c0 < c < c1) is in all_patch_v
    """
    valid_cell = [[True] * C for _ in range(R)]
    for r in range(R):
        for c in range(C):
            if Q_grid[r][c] in used_f:
                valid_cell[r][c] = False
            elif (
                V_grid[r][c] in interior_locked_v
                or V_grid[r + 1][c] in interior_locked_v
                or V_grid[r][c + 1] in interior_locked_v
                or V_grid[r + 1][c + 1] in interior_locked_v
            ):
                valid_cell[r][c] = False

    # Find largest valid cell rectangle(s) using histogram method
    best_rects = []
    heights = [0] * C
    for r in range(R):
        for c in range(C):
            heights[c] = heights[c] + 1 if valid_cell[r][c] else 0
        for c0 in range(C):
            if heights[c0] < min_dim:
                continue
            h_min = heights[c0]
            for c1 in range(c0 + 1, C + 1):
                h_min = min(h_min, heights[c1 - 1])
                if h_min < min_dim:
                    break
                w = c1 - c0
                if w >= min_dim and h_min * w >= min_area:
                    r0 = r + 1 - h_min
                    r1 = r + 1
                    best_rects.append((h_min * w, r0, r1, c0, c1))

    if not best_rects:
        return []
    best_rects.sort(reverse=True)

    # Check top candidate rectangles and trim any internal all_patch_v vertex onto the perimeter!
    results = []
    queue = [best_rects[0][1:]]
    # Also include the second-best if disjoint
    for _, r0, r1, c0, c1 in best_rects[1:6]:
        if r1 <= queue[0][0] or r0 >= queue[0][1] or c1 <= queue[0][2] or c0 >= queue[0][3]:
            queue.append((r0, r1, c0, c1))
            break

    while queue:
        r0, r1, c0, c1 = queue.pop(0)
        rh, cw = r1 - r0, c1 - c0
        if rh < min_dim or cw < min_dim or rh * cw < min_area:
            continue
        bad_v = None
        for r in range(r0 + 1, r1):
            for c in range(c0 + 1, c1):
                if V_grid[r][c] in all_patch_v:
                    bad_v = (r, c)
                    break
            if bad_v is not None:
                break
        if bad_v is None:
            results.append(extract_subgrid(Q_grid, V_grid, r0, r1, c0, c1))
        else:
            br, bc = bad_v
            # Split along br or bc so (br, bc) lies on the outer boundary of the sub-rectangles!
            cand_splits = [
                (r0, br, c0, c1),
                (br, r1, c0, c1),
                (r0, r1, c0, bc),
                (r0, r1, bc, c1),
            ]
            cand_splits.sort(key=lambda x: -(x[1] - x[0]) * (x[3] - x[2]))
            for sr0, sr1, sc0, sc1 in cand_splits[:2]:
                if (sr1 - sr0) >= min_dim and (sc1 - sc0) >= min_dim and (sr1 - sr0) * (sc1 - sc0) >= min_area:
                    queue.append((sr0, sr1, sc0, sc1))
    return results


# ---------------------------------------------------------------------------
# Ground-truth crease edge detection (from the GLB surface sample/normals)
# ---------------------------------------------------------------------------

def detect_glb_crease_edges(verts, faces, kdtree, sub_pts, sub_nrms, h_base, r2_thresh=0.08):
    """
    Detects every mesh edge (a, b) whose midpoint lies on or crosses a sharp feature crease,
    groove, or ridge in the ground-truth GLB mesh (via the normal covariance eigenvalue ratio
    lam2 / lam1 >= r2_thresh within a tight Gaussian ball of radius 0.35 * h_base around the edge midpoint).
    """
    edge_set = set()
    for f in faces:
        k = len(f)
        for i in range(k):
            a, b = int(f[i]), int(f[(i + 1) % k])
            edge_set.add((min(a, b), max(a, b)))
    e_keys = list(edge_set)
    if not e_keys:
        return set()
    e_mids = np.array([0.5 * (verts[a] + verts[b]) for (a, b) in e_keys])
    dists, nn_idx = kdtree.query(e_mids, k=10)
    cand_n = sub_nrms[nn_idx]
    w = np.exp(-0.5 * (dists / (0.35 * h_base)) ** 2) / np.maximum(dists, 1e-5)
    w /= np.sum(w, axis=1, keepdims=True)
    A_e = np.einsum("mik,mil,mi->mkl", cand_n, cand_n, w)
    evals_e = np.linalg.eigvalsh(A_e)
    r2_e = evals_e[:, 1] / np.maximum(evals_e[:, 2], 1e-9)
    return {e_keys[i] for i in range(len(e_keys)) if r2_e[i] >= r2_thresh}


# ---------------------------------------------------------------------------
# Non-destructive full-width-first 2D patch grower
# ---------------------------------------------------------------------------

def grow_patch_full_width_first(
    faces, f_normals, edge_to_f, vf, used_f, interior_locked_v, all_patch_v, crease_verts,
    seed_fi, orient_mode, step_cos, chart_cos, max_rows=50, max_cols=60, min_dim=3, min_area=12
):
    """
    Non-Destructive Full-Width-First 2D Patch Grower:
    Never trims column width C while either upward or downward growth can still advance at full width C!
    Only when BOTH directions are blocked from advancing at full width C does it snapshot the full-width
    rectangle and trim C to the wider valid sub-interval [c_l, c_r) to continue growing taller!
    Also returns ALL distinct snapshots recorded along the growth trajectory so if a larger snapshot is
    blocked by an adjacent patch or fidelity gate, smaller unblocked snapshots from the same seed are available!
    """
    if seed_fi in used_f:
        return []
    q = faces[seed_fi]
    if len(q) != 4 or any(v in interior_locked_v for v in q):
        return []
    nq = f_normals[seed_fi]
    if orient_mode == 0:
        init_grid_v = [[q[0], q[3]], [q[1], q[2]]]
    else:
        init_grid_v = [[q[0], q[1]], [q[3], q[2]]]

    def can_be_interior(v):
        return (len(vf[v]) == 4) and (v not in all_patch_v) and (v not in crease_verts) and (v not in interior_locked_v)

    def step_across_edge(curr_fi, ua, ub):
        ekey = (min(ua, ub), max(ua, ub))
        flist = [f_i for f_i in edge_to_f[ekey] if f_i != curr_fi and f_i not in used_f]
        if len(flist) != 1:
            return None, None, None
        nxt_fi = flist[0]
        nxt_q = faces[nxt_fi]
        if len(nxt_q) != 4 or any(v in interior_locked_v for v in nxt_q):
            return None, None, None
        if np.dot(f_normals[nxt_fi], f_normals[curr_fi]) < step_cos:
            return None, None, None
        if np.dot(f_normals[nxt_fi], nq) < chart_cos:
            return None, None, None
        if ua not in nxt_q or ub not in nxt_q:
            return None, None, None
        ia, ib = nxt_q.index(ua), nxt_q.index(ub)
        if (ib + 1) % 4 == ia:
            return nxt_fi, nxt_q[(ia + 1) % 4], nxt_q[(ia + 2) % 4]
        elif (ia + 1) % 4 == ib:
            return nxt_fi, nxt_q[(ib + 2) % 4], nxt_q[(ib + 1) % 4]
        return None, None, None

    row0_quads = [seed_fi]
    V_top = [init_grid_v[0][0], init_grid_v[0][1]]
    V_bot = [init_grid_v[1][0], init_grid_v[1][1]]

    cur_fi = seed_fi
    for _ in range(max_cols):
        if not (can_be_interior(V_top[-1]) or can_be_interior(V_bot[-1])):
            break
        nxt_fi, nt, nb = step_across_edge(cur_fi, V_top[-1], V_bot[-1])
        if nxt_fi is None or nt in V_top or nb in V_bot or nt in V_bot or nb in V_top:
            break
        row0_quads.append(nxt_fi)
        V_top.append(nt); V_bot.append(nb)
        cur_fi = nxt_fi

    cur_fi = seed_fi
    for _ in range(max_cols):
        if not (can_be_interior(V_top[0]) or can_be_interior(V_bot[0])):
            break
        nxt_fi, nb, nt = step_across_edge(cur_fi, V_bot[0], V_top[0])
        if nxt_fi is None or nt in V_top or nb in V_bot or nt in V_bot or nb in V_top:
            break
        row0_quads.insert(0, nxt_fi)
        V_top.insert(0, nt); V_bot.insert(0, nb)
        cur_fi = nxt_fi

    C = len(row0_quads)
    if C < min_dim:
        return []

    seed_col = row0_quads.index(seed_fi)
    Q_grid = [row0_quads]
    V_grid = [V_top, V_bot]
    existing_f = set(row0_quads)
    existing_v = set(V_top) | set(V_bot)

    snapshots = []

    def record_snapshot(Qg, Vg):
        R_s = len(Qg)
        C_s = len(Qg[0])
        if R_s >= min_dim and C_s >= min_dim and R_s * C_s >= min_area:
            for r_i in range(1, R_s):
                for c_i in range(1, C_s):
                    if not can_be_interior(Vg[r_i][c_i]):
                        return
            sc = (R_s * C_s) * (min(R_s, C_s) ** 0.5)
            snapshots.append((sc, R_s, C_s, [r[:] for r in Qg], [r[:] for r in Vg], nq))

    def get_down_interval():
        prev_q_row = Q_grid[-1]
        prev_v_row = V_grid[-1]
        col_steps = [None] * C
        for c in range(C):
            ua, ub = prev_v_row[c], prev_v_row[c + 1]
            nxt_fi, na, nb = step_across_edge(prev_q_row[c], ua, ub)
            if nxt_fi is not None and nxt_fi not in existing_f and na not in existing_v and nb not in existing_v:
                col_steps[c] = (nxt_fi, na, nb)
        if col_steps[seed_col] is None:
            return None, 0, 0
        c_l = seed_col
        while c_l > 0 and col_steps[c_l - 1] is not None and can_be_interior(prev_v_row[c_l]) and col_steps[c_l - 1][2] == col_steps[c_l][1]:
            c_l -= 1
        c_r = seed_col + 1
        while c_r < C and col_steps[c_r] is not None and can_be_interior(prev_v_row[c_r]) and col_steps[c_r - 1][2] == col_steps[c_r][1]:
            c_r += 1
        if c_r - c_l < min_dim:
            return None, 0, 0
        sub_steps = col_steps[c_l:c_r]
        w = c_r - c_l
        next_q = [sub_steps[c][0] for c in range(w)]
        next_v = [sub_steps[0][1]] + [sub_steps[c][2] for c in range(w)]
        if len(set(next_q)) != w or len(set(next_v)) != w + 1:
            return None, 0, 0
        return (next_q, next_v), c_l, c_r

    def get_up_interval():
        top_q_row = Q_grid[0]
        top_v_row = V_grid[0]
        col_steps = [None] * C
        for c in range(C):
            ua, ub = top_v_row[c + 1], top_v_row[c]
            nxt_fi, nb, na = step_across_edge(top_q_row[c], ua, ub)
            if nxt_fi is not None and nxt_fi not in existing_f and na not in existing_v and nb not in existing_v:
                col_steps[c] = (nxt_fi, na, nb)
        if col_steps[seed_col] is None:
            return None, 0, 0
        c_l = seed_col
        while c_l > 0 and col_steps[c_l - 1] is not None and can_be_interior(top_v_row[c_l]) and col_steps[c_l - 1][2] == col_steps[c_l][1]:
            c_l -= 1
        c_r = seed_col + 1
        while c_r < C and col_steps[c_r] is not None and can_be_interior(top_v_row[c_r]) and col_steps[c_r - 1][2] == col_steps[c_r][1]:
            c_r += 1
        if c_r - c_l < min_dim:
            return None, 0, 0
        sub_steps = col_steps[c_l:c_r]
        w = c_r - c_l
        prev_q = [sub_steps[c][0] for c in range(w)]
        prev_v = [sub_steps[0][1]] + [sub_steps[c][2] for c in range(w)]
        if len(set(prev_q)) != w or len(set(prev_v)) != w + 1:
            return None, 0, 0
        return (prev_q, prev_v), c_l, c_r

    while len(Q_grid) < max_rows:
        # 1. Try advancing at FULL current width C (zero trimming!) in both directions first!
        advanced_full = False
        down_res, dl, dr = get_down_interval()
        if down_res is not None and dl == 0 and dr == C:
            nq_row, nv_row = down_res
            Q_grid.append(nq_row)
            V_grid.append(nv_row)
            existing_f.update(nq_row)
            existing_v.update(nv_row)
            advanced_full = True

        if len(Q_grid) < max_rows:
            up_res, ul, ur = get_up_interval()
            if up_res is not None and ul == 0 and ur == C:
                pq_row, pv_row = up_res
                Q_grid.insert(0, pq_row)
                V_grid.insert(0, pv_row)
                existing_f.update(pq_row)
                existing_v.update(pv_row)
                advanced_full = True

        if advanced_full:
            continue

        # 2. Neither direction can advance at full width C! Record snapshot before trimming!
        record_snapshot(Q_grid, V_grid)

        down_res, dl, dr = get_down_interval()
        up_res, ul, ur = get_up_interval()
        w_down = (dr - dl) if down_res is not None else 0
        w_up = (ur - ul) if up_res is not None else 0

        if w_down == 0 and w_up == 0:
            break

        if w_down >= w_up:
            nq_row, nv_row = down_res
            Q_grid = [r[dl:dr] for r in Q_grid] + [nq_row]
            V_grid = [r[dl:dr + 1] for r in V_grid] + [nv_row]
            existing_f = set(f_i for r in Q_grid for f_i in r)
            existing_v = set(v_i for r in V_grid for v_i in r)
            seed_col -= dl
            C = dr - dl
        else:
            pq_row, pv_row = up_res
            Q_grid = [pq_row] + [r[ul:ur] for r in Q_grid]
            V_grid = [pv_row] + [r[ul:ur + 1] for r in V_grid]
            existing_f = set(f_i for r in Q_grid for f_i in r)
            existing_v = set(v_i for r in V_grid for v_i in r)
            seed_col -= ul
            C = ur - ul

    record_snapshot(Q_grid, V_grid)
    return snapshots


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def coarsen_all_scales_ruler_straight(verts, faces, kdtree, sub_pts, sub_nrms, h_base, is_cad=True, is_rack=False):
    verts = verts.copy()
    faces = [list(f) for f in faces if len(f) >= 3]
    interior_locked_v = set()
    all_patch_v = set()

    total_patches = 0
    total_removed = 0

    if is_cad:
        if is_rack:
            pass_configs = [
                (3, 12, 60, 80, 10.0, 12.0, 0.08, 2, False, 0.08, 10.0),
                (3, 10, 40, 60,  9.5, 11.5, 0.08, 1, False, 0.08, 10.0),
            ]
        else:
            pass_configs = [
                (4, 16, 60, 80, 12.0, 16.0, 0.08, 2, False, 0.10, 14.0),
                (3, 12, 45, 65, 16.0, 28.0, 0.11, 1, False, 0.12, 16.0),
                (3, 12, 35, 50, 20.0, 36.0, 0.13, 1, False, 0.13, 18.0),
                (2,  6, 30, 40, 18.0, 32.0, 0.12, 1, True,  0.12, 16.0),
            ]
        strides_to_try = [(4, 4), (4, 3), (3, 4), (3, 3), (3, 2), (2, 3), (2, 2), (2, 1), (1, 2)]
        max_ar = 6.5
    else:
        pass_configs = [
            (4, 16, 28, 28, 30.0, 68.0, 0.0, 2, False, 0.28, 30.0),
            (3, 12, 22, 22, 30.0, 64.0, 0.0, 1, False, 0.30, 32.0),
            (3, 12, 16, 16, 32.0, 60.0, 0.0, 1, False, 0.34, 35.0),
            (2,  6, 18, 18, 30.0, 56.0, 0.0, 1, True,  0.32, 34.0),
            # Mop-up passes: after the 4 above, whatever's left is small,
            # irregular leftover patches BETWEEN the accepted big panels --
            # greedy heap packing locks out neighbors once a panel claims
            # their shared vertices, so loosening the earlier passes' own
            # gates barely helps (confirmed: widening target_faces_for_h_base
            # 5.4x only moved patch count 933->951). What actually helps is
            # retrying the leftover gaps themselves, at the smallest viable
            # block size (2x2) with seed_step=1 (try every remaining quad,
            # not every other) and much looser fidelity gates -- a small
            # leftover gap, almost by definition, sits on gentler local
            # curvature than whatever beat it to the bigger neighboring
            # panels, so it can afford a looser gate without real quality
            # loss.
            (2, 4, 14, 14, 35.0, 70.0, 0.0, 1, True, 0.42, 48.0),
            (2, 4,  8,  8, 42.0, 75.0, 0.0, 1, True, 0.55, 60.0),
        ]
        strides_to_try = [(4, 4), (4, 3), (3, 4), (3, 3), (3, 2), (2, 3), (2, 2), (2, 1), (1, 2)]
        max_ar = 5.0

    for min_dim, min_area, m_rows, m_cols, step_deg, chart_deg, r2_thr, seed_step, is_strip, chord_r, nrm_deg in pass_configs:
        max_chord_dist = chord_r * h_base
        min_normal_cos = np.cos(np.radians(nrm_deg))
        crease_edges = detect_glb_crease_edges(verts, faces, kdtree, sub_pts, sub_nrms, h_base, r2_thresh=r2_thr) if (is_cad and r2_thr > 0) else set()

        f_normals = []
        edge_to_f = defaultdict(list)
        vf = defaultdict(list)
        for fi, f in enumerate(faces):
            pts = verts[f]
            n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
            if len(f) == 4:
                n += np.cross(pts[2] - pts[0], pts[3] - pts[0])
            ln = np.linalg.norm(n)
            f_normals.append(n / ln if ln > 1e-12 else np.array([0.0, 0.0, 1.0]))
            for k in range(len(f)):
                a, b = f[k], f[(k + 1) % len(f)]
                ek = (min(a, b), max(a, b))
                if ek not in crease_edges:
                    edge_to_f[ek].append(fi)
                vf[a].append(fi)
        f_normals = np.array(f_normals)

        step_cos = np.cos(np.radians(step_deg))
        chart_cos = np.cos(np.radians(chart_deg))

        heap = []
        seen_rect_keys = set()
        tie_id = 0

        def push_rect(R_s, C_s, Qg, Vg, nq):
            nonlocal tie_id
            if R_s < min_dim or C_s < min_dim or R_s * C_s < min_area or (R_s < 3 and C_s < 3):
                return
            if not is_strip and (R_s < 4 and C_s < 4):
                return
            rkey = (R_s, C_s, Qg[0][0], Qg[0][-1], Qg[-1][0], Qg[-1][-1])
            if rkey in seen_rect_keys:
                return
            seen_rect_keys.add(rkey)
            sc = (R_s * C_s) * (min(R_s, C_s) ** 0.5)
            tie_id += 1
            heapq.heappush(heap, (-sc, tie_id, R_s, C_s, Qg, Vg, nq))

        for sfi in range(0, len(faces), seed_step):
            if len(faces[sfi]) != 4:
                continue
            for om in (0, 1):
                snaps = grow_patch_full_width_first(
                    faces, f_normals, edge_to_f, vf, set(), interior_locked_v, all_patch_v, set(),
                    sfi, om, step_cos, chart_cos, max_rows=m_rows, max_cols=m_cols, min_dim=min_dim, min_area=min_area
                )
                for sc_s, R_s, C_s, Qg, Vg, nq in snaps:
                    push_rect(R_s, C_s, Qg, Vg, nq)

        used_f = set()
        added_faces = []

        while heap:
            neg_sc, _, R, C, Q_grid, V_grid, nq = heapq.heappop(heap)
            q_flat = [fi for r_q in Q_grid for fi in r_q]
            v_all = set(v for r_v in V_grid for v in r_v)
            v_int = set(V_grid[r][c] for r in range(1, R) for c in range(1, C))

            if any(fi in used_f for fi in q_flat) or (v_all & interior_locked_v) or (v_int & all_patch_v):
                sub_grids = crop_to_free_subgrids(R, C, Q_grid, V_grid, used_f, interior_locked_v, all_patch_v, min_dim, min_area)
                for R_sub, C_sub, Q_sub, V_sub in sub_grids:
                    push_rect(R_sub, C_sub, Q_sub, V_sub, nq)
                continue

            q0_orig = faces[Q_grid[0][0]]
            test_q = [V_grid[0][0], V_grid[1][0], V_grid[1][1], V_grid[0][1]]
            n_orig = np.cross(verts[q0_orig[1]] - verts[q0_orig[0]], verts[q0_orig[2]] - verts[q0_orig[0]])
            n_test = np.cross(verts[test_q[1]] - verts[test_q[0]], verts[test_q[2]] - verts[test_q[0]])
            flip_winding = np.dot(n_orig, n_test) < 0

            def orient_face(f_verts):
                return f_verts[::-1] if flip_winding else f_verts

            accepted_patch_faces = None

            if is_strip and (C == 2 or R == 2):
                min_red = 1 if (R * C == 6) else 2
                if C == 2 and R >= 3:
                    cand_f, r_idx_s, c_idx_s = build_full_width_strip_faces(verts, R, C, V_grid, 2, orient_face)
                    if cand_f is not None and len(cand_f) <= len(q_flat) - min_red:
                        if general_subblock_fidelity_gate(verts, R, C, Q_grid, V_grid, f_normals, r_idx_s, c_idx_s, cand_f, max_chord_dist, min_normal_cos, max_ar=2.35):
                            accepted_patch_faces = cand_f
                if accepted_patch_faces is None and R == 2 and C >= 3:
                    V_T = [[V_grid[r][c] for r in range(R + 1)] for c in range(C + 1)]
                    of_T = lambda fv: orient_face(fv[::-1])
                    cand_f, c_idx_T, r_idx_T = build_full_width_strip_faces(verts, C, R, V_T, 2, of_T)
                    if cand_f is not None and len(cand_f) <= len(q_flat) - min_red:
                        if general_subblock_fidelity_gate(verts, R, C, Q_grid, V_grid, f_normals, r_idx_T, c_idx_T, cand_f, max_chord_dist, min_normal_cos, max_ar=2.35):
                            accepted_patch_faces = cand_f

            if accepted_patch_faces is None and R >= 3 and C >= 3:
                for (sr_try, sc_try) in strides_to_try:
                    r_idx, c_idx = compute_ruler_straight_indices(R, C, sr_try, sc_try)
                    if r_idx is None:
                        continue
                    new_pos = ruler_straight_interior_positions(verts, R, C, V_grid, r_idx, c_idx)
                    saved_pos = {vid: verts[vid].copy() for vid in new_pos}
                    for vid, pos in new_pos.items():
                        verts[vid] = pos

                    cand_faces = build_patch_faces_from_indices(verts, R, C, V_grid, r_idx, c_idx, orient_face)
                    min_reduction = 1 if (R * C <= 15) else 2
                    if cand_faces is not None and len(cand_faces) <= len(q_flat) - min_reduction:
                        if general_subblock_fidelity_gate(verts, R, C, Q_grid, V_grid, f_normals, r_idx, c_idx, cand_faces, max_chord_dist, min_normal_cos, max_ar=max_ar):
                            accepted_patch_faces = cand_faces
                            break

                    for vid, pos in saved_pos.items():
                        verts[vid] = pos

            if accepted_patch_faces is None:
                if R >= C and R >= 5:
                    mid = R // 2
                    for r0, r1 in [(0, mid + 1), (mid - 1, R)]:
                        if r1 - r0 >= min_dim:
                            R_sub, C_sub, Q_sub, V_sub = extract_subgrid(Q_grid, V_grid, r0, r1, 0, C)
                            push_rect(R_sub, C_sub, Q_sub, V_sub, nq)
                elif C > R and C >= 5:
                    mid = C // 2
                    for c0, c1 in [(0, mid + 1), (mid - 1, C)]:
                        if c1 - c0 >= min_dim:
                            R_sub, C_sub, Q_sub, V_sub = extract_subgrid(Q_grid, V_grid, 0, R, c0, c1)
                            push_rect(R_sub, C_sub, Q_sub, V_sub, nq)
                continue

            used_f.update(q_flat)
            added_faces.extend(accepted_patch_faces)
            interior_locked_v.update(v_int)
            all_patch_v.update(v_all)
            total_patches += 1
            total_removed += (len(q_flat) - len(accepted_patch_faces))

        faces = [f for fi, f in enumerate(faces) if fi not in used_f] + added_faces

    used_v = sorted(set(v for f in faces for v in f))
    remap = {old_v: new_i for new_i, old_v in enumerate(used_v)}
    clean_verts = verts[used_v]
    clean_faces = [[remap[v] for v in f] for f in faces]
    clean_locked = {remap[v] for v in interior_locked_v if v in remap}
    print(f"  [All-Scales Ruler-Straight Coarsener]: {total_patches} multi-quad panels coarsened (-{total_removed} faces)")
    return clean_verts, clean_faces, clean_locked
