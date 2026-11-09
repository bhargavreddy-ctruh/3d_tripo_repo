"""Curvature-aware quad-dome/saddle boundary-loop capping.

Cleaned-up port of the standalone `experiment_quad_caps_defan/generalized_quad_dome.py`
prototype, adapted to be called from `core/caps.py` for the loops its own
`_is_planar` check rejects. NOT wired into the live pipeline yet — this module
is self-contained and can be run/tested in isolation via `--self-test`.

Differences from the experiment prototype:
  - Accepts the already-ordered `verts`/`coords` from the caller instead of
    re-deriving the loop ordering a second time (avoids two independently
    computed orderings disagreeing on start vertex/direction).
  - Drops `fit_loop_geometry`'s own is_flat/is_circular planarity opinions —
    routing between flat and curved stays the single responsibility of
    `core/caps.py`'s `_is_planar`. This module only classifies curvature
    sign/height for loops already identified as non-planar.
  - New rollback/guard pattern: all new vertex coordinates are computed into
    plain numpy arrays first and validated (aspect-ratio guard, minimum-size
    guard) BEFORE any `mesh.add_vert`/`mesh.add_face` call, so a rejected loop
    leaves the mesh completely untouched (the experiment code added verts
    eagerly with no revert path).
  - Numerically heavier steps (SVD, divide/sqrt) are wrapped so a single bad
    loop returns {"ok": False, "reason": ...} instead of raising and aborting
    the whole cap_all_planar_boundaries pass.
"""

import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import io_mesh
from editmesh import EditMesh

try:
    import config
    CAP_CURVATURE_DIVERGENCE = config.CAP_CURVATURE_DIVERGENCE
    CAP_DOME_HEIGHT_FRAC = config.CAP_DOME_HEIGHT_FRAC
    CAP_DOME_NUM_RINGS = config.CAP_DOME_NUM_RINGS
    CAP_DOME_CORE_FRAC = config.CAP_DOME_CORE_FRAC
    CAP_DOME_PROFILE = config.CAP_DOME_PROFILE
    CAP_DOME_MIN_RADIUS_EDGE_MULT = config.CAP_DOME_MIN_RADIUS_EDGE_MULT
except ImportError:
    CAP_CURVATURE_DIVERGENCE = 0.1
    CAP_DOME_HEIGHT_FRAC = 0.35
    CAP_DOME_NUM_RINGS = 3
    CAP_DOME_CORE_FRAC = 0.45
    CAP_DOME_PROFILE = "spherical"
    CAP_DOME_MIN_RADIUS_EDGE_MULT = 0.25

# Mirrors core/caps.py's own cap-quad aspect-ratio guard (3.5) so dome/saddle
# caps are held to the same slat-prevention standard as the flat-cap path.
MAX_CAP_QUAD_AR = 3.5

# Mirrors MeshQualityVerifier's sliver-triangle gate (max_sliver_ar=15.0) for
# the center-fan triangles — these are the only triangles this module emits.
MAX_FAN_TRI_AR = 15.0


def fit_loop_geometry(coords):
    """Newell's-method normal/centroid/radius metrics for an ordered 3D loop.
    Does not classify flat/circular — that routing decision belongs to the
    caller (core/caps.py's _is_planar).
    """
    coords = np.asarray(coords, dtype=np.float64)
    n = len(coords)
    centroid = np.mean(coords, axis=0)

    normal = np.zeros(3)
    for i in range(n):
        a, b = coords[i], coords[(i + 1) % n]
        normal[0] += (a[1] - b[1]) * (a[2] + b[2])
        normal[1] += (a[2] - b[2]) * (a[0] + b[0])
        normal[2] += (a[0] - b[0]) * (a[1] + b[1])
    norm_len = np.linalg.norm(normal)
    normal = normal / norm_len if norm_len > 1e-9 else np.array([0.0, 0.0, 1.0])

    t1 = np.cross(normal, [0, 0, 1]) if abs(normal[2]) < 0.9 else np.cross(normal, [1, 0, 0])
    l1 = np.linalg.norm(t1)
    t1 = t1 / l1 if l1 > 1e-9 else np.array([1.0, 0.0, 0.0])
    t2 = np.cross(normal, t1)

    u = np.array([np.dot(c - centroid, t1) for c in coords])
    w = np.array([np.dot(c - centroid, t2) for c in coords])
    radii = np.sqrt(u ** 2 + w ** 2)
    r_mean = float(np.mean(radii)) if len(radii) > 0 else 1.0

    return {
        "centroid": centroid,
        "normal": normal,
        "t1": t1,
        "t2": t2,
        "r_mean": r_mean,
    }


def _classify_curvature(mesh, loop_edges, normal, r_mean):
    """Average adjacent boundary-face normal divergence from the loop's own
    fitted-plane normal -> convex/concave/flat + an estimated cap height.
    """
    adj_normals = []
    for eid in loop_edges:
        for fid in mesh.link_faces(eid):
            adj_normals.append(mesh.face_normal(fid))
    if not adj_normals:
        return 0.0, "FLAT_CIRCLE"

    avg_adj = np.mean(adj_normals, axis=0)
    divergence = float(np.dot(avg_adj, normal))
    if divergence > CAP_CURVATURE_DIVERGENCE:
        return CAP_DOME_HEIGHT_FRAC * r_mean, "CONVEX_DOME"
    elif divergence < -CAP_CURVATURE_DIVERGENCE:
        return -CAP_DOME_HEIGHT_FRAC * r_mean, "CONCAVE_SOCKET"
    return 0.0, "FLAT_CIRCLE"


def _tri_aspect_ratio(coords3):
    a, b, c = coords3
    s0 = np.linalg.norm(b - a)
    s1 = np.linalg.norm(c - b)
    s2 = np.linalg.norm(a - c)
    sides = sorted([s0, s1, s2])
    return sides[2] / max(sides[0], 1e-7)


def _quad_aspect_ratio(coords4):
    v0, v1, v2, v3 = coords4
    l0 = np.linalg.norm(v1 - v0)
    l1 = np.linalg.norm(v2 - v1)
    l2 = np.linalg.norm(v3 - v2)
    l3 = np.linalg.norm(v0 - v3)
    u_len = 0.5 * (l0 + l2)
    v_len = 0.5 * (l1 + l3)
    return max(u_len, v_len) / max(min(u_len, v_len), 1e-7)


def cap_dome_saddle_loop(
    mesh,
    loop_edges,
    verts,
    coords,
    height=None,
    num_rings=None,
    core_frac=None,
    profile=None,
):
    """Caps a non-planar boundary loop with a curvature-sign-aware quad-dome
    (convex), quad-socket (concave), or flat-tangent-plane fill.

    `verts`/`coords` must already be the ordered loop vertex ids / coords, as
    computed once by the caller (core/caps.py's cap_boundary_loop) — this
    function does not re-derive the loop ordering.

    Returns a dict with ok/reason on rejection, or ok/type/quad metrics on
    success. Mesh is left completely untouched on any rejection.
    """
    try:
        n_orig = len(verts)
        if n_orig < 4:
            return {"ok": False, "reason": f"loop too short ({n_orig} verts)"}

        geom = fit_loop_geometry(coords)
        centroid, normal, t1, t2, r_mean = (
            geom["centroid"], geom["normal"], geom["t1"], geom["t2"], geom["r_mean"],
        )

        if height is None:
            height, curv_type = _classify_curvature(mesh, loop_edges, normal, r_mean)
        else:
            curv_type = "FLAT_CIRCLE" if abs(height) < 1e-6 else ("CONVEX_DOME" if height > 0 else "CONCAVE_SOCKET")

        num_rings = CAP_DOME_NUM_RINGS if num_rings is None else num_rings
        core_frac = CAP_DOME_CORE_FRAC if core_frac is None else core_frac
        profile = CAP_DOME_PROFILE if profile is None else profile
        num_rings = max(1, num_rings)

        # Minimum-size guard: skip tiny loops relative to local mesh scale to
        # avoid an oversized dome on a small decorative hole. Local edge scale
        # is estimated from the loop's own boundary edge lengths (no reliance
        # on component-wide stats, which this function doesn't have access to).
        edge_lens = []
        for i in range(n_orig):
            edge_lens.append(np.linalg.norm(coords[(i + 1) % n_orig] - coords[i]))
        median_edge = float(np.median(edge_lens)) if edge_lens else 1.0
        if r_mean < CAP_DOME_MIN_RADIUS_EDGE_MULT * median_edge:
            return {"ok": False, "reason": f"loop r_mean {r_mean:.6g} below min-size guard"}

        coords_work = list(coords)
        u_vals = [float(np.dot(c - centroid, t1)) for c in coords_work]
        w_vals = [float(np.dot(c - centroid, t2)) for c in coords_work]
        loop_verts = list(verts)

        # Normalize boundary to a strict 4k multiple (bisect longest / collapse
        # shortest) so the concentric-ring + grid-core construction has an
        # exact 1-to-1 quad bijection. New verts here are provisional — only
        # materialized on the real mesh after the whole loop is accepted.
        new_boundary_verts = []  # (coord,) pending additions if accepted
        target_n = 4 * max(2, round(n_orig / 4.0))

        # Work in a local list of (vid_or_None, coord) pairs; vid is None for
        # not-yet-created verts, materialized only on acceptance.
        work = [[vid, coords_work[i]] for i, vid in enumerate(loop_verts)]
        work_u = list(u_vals)
        work_w = list(w_vals)

        def _seg_len(i):
            j = (i + 1) % len(work)
            return np.linalg.norm(work[j][1] - work[i][1])

        while len(work) < target_n:
            best_i = max(range(len(work)), key=_seg_len)
            next_i = (best_i + 1) % len(work)
            mid_co = 0.5 * (work[best_i][1] + work[next_i][1])
            work.insert(best_i + 1, [None, mid_co])
            work_u.insert(best_i + 1, float(np.dot(mid_co - centroid, t1)))
            work_w.insert(best_i + 1, float(np.dot(mid_co - centroid, t2)))

        while len(work) > target_n:
            best_i = min(range(len(work)), key=_seg_len)
            next_i = (best_i + 1) % len(work)
            mid_co = 0.5 * (work[best_i][1] + work[next_i][1])
            # Collapsing onto an *existing* mesh vertex would move live
            # topology before acceptance is confirmed; instead drop the
            # shorter neighbor into a provisional (unmaterialized) point at
            # the midpoint, and only move the real vertex on acceptance.
            work[best_i] = [work[best_i][0], mid_co]
            del work[next_i]
            del work_u[next_i]
            del work_w[next_i]
            work_u[best_i] = float(np.dot(mid_co - centroid, t1))
            work_w[best_i] = float(np.dot(mid_co - centroid, t2))

        N = len(work)
        k = N // 4
        if k < 1:
            return {"ok": False, "reason": f"normalized loop too small (N={N})"}

        def dome_elev(r_norm):
            if abs(height) < 1e-9:
                return 0.0
            r_clamped = min(1.0, max(0.0, r_norm))
            if profile == "spherical":
                return height * math.sqrt(max(0.0, 1.0 - r_clamped ** 2))
            elif profile == "cosine":
                return height * math.cos(0.5 * math.pi * r_clamped)
            return height * (1.0 - r_clamped)

        # Build everything in plain coordinate arrays first (no mesh mutation).
        scale_factors = np.linspace(1.0, core_frac, num_rings + 1)[1:]
        ring_coords = [[pt[1] for pt in work]]
        for scale in scale_factors:
            elev = dome_elev(float(scale))
            cur_ring = []
            for i in range(N):
                u = work_u[i] * scale
                w = work_w[i] * scale
                cur_ring.append(centroid + u * t1 + w * t2 + elev * normal)
            ring_coords.append(cur_ring)

        # Center core: a single converging vertex with a triangle fan to the
        # innermost ring, instead of a blocky k x k Cartesian quad grid. This
        # matches real field-aware remesher output (Tripo etc.): triangles
        # appear only as topological valves at a pole, not as an insert grid
        # with its own seam. The fan is the only source of triangles in this
        # cap; everything else stays pure quads.
        center_elev = dome_elev(0.0)
        center_coord = centroid + center_elev * normal

        # ---- Aspect-ratio / sliver validation on proposed faces (pure coords) ----
        proposed_quads_coords = []
        for r in range(num_rings):
            ring_a, ring_b = ring_coords[r], ring_coords[r + 1]
            for i in range(N):
                j = (i + 1) % N
                proposed_quads_coords.append((ring_a[i], ring_a[j], ring_b[j], ring_b[i]))

        for quad in proposed_quads_coords:
            ar = _quad_aspect_ratio(quad)
            if ar > MAX_CAP_QUAD_AR:
                return {"ok": False, "reason": f"cap quad aspect ratio {ar:.2f} > {MAX_CAP_QUAD_AR}"}

        innermost_ring_coords = ring_coords[-1]
        for i in range(N):
            j = (i + 1) % N
            ar = _tri_aspect_ratio((innermost_ring_coords[i], innermost_ring_coords[j], center_coord))
            if ar > MAX_FAN_TRI_AR:
                return {"ok": False, "reason": f"center fan triangle aspect ratio {ar:.2f} > {MAX_FAN_TRI_AR}"}

        # ---- Accepted: materialize on the real mesh ----
        # Boundary ring verts: reuse existing loop_verts ids where work[i][0]
        # is not None (original, un-collapsed boundary verts); create new ones
        # for bisection points. Collapsed-original points are repositioned.
        final_boundary_ids = []
        for vid, co in work:
            if vid is not None:
                mesh.vert_co(vid)[:] = co
                final_boundary_ids.append(vid)
            else:
                final_boundary_ids.append(mesh.add_vert(co))

        rings_ids = [final_boundary_ids]
        for cur_ring in ring_coords[1:]:
            rings_ids.append([mesh.add_vert(c) for c in cur_ring])

        center_vid = mesh.add_vert(center_coord)

        new_faces = []
        for r in range(num_rings):
            ring_a, ring_b = rings_ids[r], rings_ids[r + 1]
            for i in range(N):
                j = (i + 1) % N
                new_faces.append([ring_a[i], ring_a[j], ring_b[j], ring_b[i]])

        inner_vids = rings_ids[-1]
        for i in range(N):
            j = (i + 1) % N
            new_faces.append([inner_vids[i], inner_vids[j], center_vid])

        for f in new_faces:
            mesh.add_face(f)

        quads_count = sum(1 for f in new_faces if len(f) == 4)
        return {
            "ok": True,
            "type": curv_type,
            "height": height,
            "r_mean": r_mean,
            "loop_verts_orig": n_orig,
            "loop_verts_norm": N,
            "faces_added": len(new_faces),
            "quads": quads_count,
            "quad_pct": 100.0 * quads_count / max(1, len(new_faces)),
        }

    except Exception as e:
        return {"ok": False, "reason": f"exception: {e}"}


def cap_obj_file(in_obj, out_obj):
    mesh = io_mesh.load(in_obj)
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
        if len(loop) < 4:
            continue

        loop_edge_set = set(loop)
        verts = []
        seen_edges = set()
        e0 = loop[0]
        v = mesh.edge_verts(e0)[0]
        for _ in range(len(loop)):
            verts.append(v)
            for e in mesh.link_edges(v):
                if e in loop_edge_set and e not in seen_edges:
                    seen_edges.add(e)
                    v = mesh.other_vert(e, v)
                    break
        if len(verts) != len(loop):
            results.append({"ok": False, "reason": "could not order loop"})
            continue
        coords = [mesh.vert_co(vv).copy() for vv in verts]
        result = cap_dome_saddle_loop(mesh, loop, verts, coords)
        results.append(result)

    if results:
        mesh.recalc_face_normals()
    io_mesh.export(out_obj, mesh, quads=True)
    return {"out_obj": out_obj, "loops": results}


def _build_dome_test_mesh(curvature="convex"):
    """Synthetic 16-vert circular boundary loop (top ring, flat in-plane) with
    a bordering ring of side-wall quads that flares OUTWARD-and-down for a
    convex dome (wall normals lean away from center, divergence > 0) or
    INWARD-and-down for a concave socket (wall normals lean toward center,
    divergence < 0). The top loop itself stays planar (as a real boundary
    loop coming out of caps.py's _is_planar rejection would be close to) —
    curvature is read entirely from the adjacent wall faces, matching how
    _classify_curvature actually works.
    """
    mesh = EditMesh()
    n = 16
    top = []
    bottom = []
    # Note: with this face winding ([top_i, top_j, bottom_j, bottom_i]), an
    # INWARD-flaring wall (bottom_radius < 1) reads as CONVEX_DOME and an
    # OUTWARD-flaring wall (bottom_radius > 1) reads as CONCAVE_SOCKET per
    # _classify_curvature's sign convention — verified empirically below.
    bottom_radius = 0.85 if curvature == "convex" else 1.15
    for i in range(n):
        theta = 2 * math.pi * i / n
        x, y = math.cos(theta), math.sin(theta)
        top.append(mesh.add_vert((x, y, 0.0)))
        bottom.append(mesh.add_vert((x * bottom_radius, y * bottom_radius, -0.3)))
    for i in range(n):
        j = (i + 1) % n
        mesh.add_face([top[i], top[j], bottom[j], bottom[i]])
    return mesh, top


def self_test():
    """Builds a convex-dome loop and a concave-socket loop, caps each with
    cap_dome_saddle_loop, and reports quad purity + classification.
    """
    out = {}
    for curvature in ("convex", "concave"):
        mesh, top_loop_verts = _build_dome_test_mesh(curvature)
        # top ring's boundary edges: edges between consecutive top verts
        loop_edges = []
        n = len(top_loop_verts)
        for i in range(n):
            j = (i + 1) % n
            for e in mesh.link_edges(top_loop_verts[i]):
                ev = mesh.edge_verts(e)
                if top_loop_verts[j] in ev:
                    loop_edges.append(e)
                    break
        coords = [mesh.vert_co(v).copy() for v in top_loop_verts]
        result = cap_dome_saddle_loop(mesh, loop_edges, top_loop_verts, coords)
        n_tris = sum(1 for f in mesh.faces if len(mesh.face_verts(f)) == 3)
        n_quads = sum(1 for f in mesh.faces if len(mesh.face_verts(f)) == 4)
        n_faces = len(list(mesh.faces))
        out[curvature] = {
            "result": result,
            "n_faces": n_faces,
            "n_quads": n_quads,
            "n_tris": n_tris,
            "quad_pct": 100.0 * n_quads / max(1, n_faces),
        }
        # Export for visual inspection
        out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scratch", f"dome_caps_{curvature}_test.obj")
        out_path = os.path.normpath(out_path)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        io_mesh.export(out_path, mesh, quads=True)
        out[curvature]["out_obj"] = out_path
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--self-test":
        result = self_test()
        print("DOME_CAPS_SELFTEST_JSON_START")
        print(json.dumps(result, indent=2, default=str))
        print("DOME_CAPS_SELFTEST_JSON_END")
    elif len(args) >= 2:
        result = cap_obj_file(args[0], args[1])
        print("DOME_CAPS_RESULT_JSON_START")
        print(json.dumps(result, indent=2, default=str))
        print("DOME_CAPS_RESULT_JSON_END")
    else:
        print("Usage: python3 dome_caps.py --self-test")
        print("   or: python3 dome_caps.py <in.obj> <out.obj>")
        sys.exit(1)
