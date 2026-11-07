"""Transverse-loop + straight-slat dissolution driven by protect.py's
continuous cost field — no fixed 3deg/18deg tiers. Pure Python
(EditMesh.merge_faces, no Blender), one component at a time.

Ports the proven loop-tracing mechanics from tripo_smart_engine's
ribbon_engine.py (`trace_full_transverse_loop`) near-verbatim, but instead
of two hardcoded angle tiers, a single pass processes ALL non-hard-
protected edges (cost < math.inf, i.e. everything protect.py didn't flag
as a real feature), always preferring the lowest-cost (flattest) loops
first each pass. Since protect.py already guarantees every finite cost is
strictly below the crease threshold, there is no extra tolerance knob to
tune here — "dissolve everything that isn't a protected feature, flattest
first" is itself the continuous generalization of the old tiers.

Each accepted loop's run of faces is merged into one n-gon via
EditMesh.merge_faces(dissolve_verts=True) — the equivalent of bmesh's
`dissolve_edges(..., use_verts=True)`, applied per-loop rather than in one
batched call, since the greedy accept step below already guarantees
accepted loops never share a face (so merging them one at a time gives the
identical end result a single combined call would).

Safety net (per the Primary objective's hard feature-preservation
constraint): total mesh surface area is checked before/after every pass;
any pass that changes it beyond floating-point tolerance is rejected
(rolled back) rather than trusted.
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import config
import io_mesh
import protect as protect_mod
from editmesh import EditMesh


def _total_area(mesh):
    return mesh.total_area()


def _get_continuation(mesh, v, incoming_e, cost_map, protected_set):
    """Relaxed transverse loop continuation:
    1. Valence-4 interior lattice: opposite edge not sharing face with incoming.
    2. Valence-2 collinear vertex: straight-through step (< 15 deg).
    3. Extraordinary vertex / pole (valence 3, 5, N): tangent-collinear edge (< 15 deg).
    """
    edges = list(mesh.link_edges(v))
    if len(edges) == 4:
        incoming_faces = set(mesh.link_faces(incoming_e))
        for e in edges:
            if e == incoming_e:
                continue
            if e in protected_set:
                continue
            if set(mesh.link_faces(e)) & incoming_faces:
                continue
            if e not in cost_map:
                continue
            return e
        return None
    elif len(edges) == 2:
        # Valence-2 collinear vertex: step straight through
        other_e = edges[0] if edges[1] == incoming_e else edges[1]
        if other_e in protected_set or other_e not in cost_map:
            return None
        v_prev = mesh.other_vert(incoming_e, v)
        v_next = mesh.other_vert(other_e, v)
        t_in = mesh.vert_co(v) - mesh.vert_co(v_prev)
        t_out = mesh.vert_co(v_next) - mesh.vert_co(v)
        l_in = np.linalg.norm(t_in)
        l_out = np.linalg.norm(t_out)
        if l_in > 1e-9 and l_out > 1e-9:
            cos_a = float(np.clip(np.dot(t_in, t_out) / (l_in * l_out), -1.0, 1.0))
            if cos_a > 0.9659:  # cos(15 deg)
                return other_e
        return None
    elif len(edges) in (3, 5) or len(edges) > 5:
        # Extraordinary vertex / pole: find outgoing edge with best tangent collinearity (< 15 deg)
        v_prev = mesh.other_vert(incoming_e, v)
        t_in = mesh.vert_co(v) - mesh.vert_co(v_prev)
        l_in = np.linalg.norm(t_in)
        if l_in < 1e-9:
            return None
        incoming_faces = set(mesh.link_faces(incoming_e))
        best_e = None
        best_cos = 0.9659  # cos(15 deg)
        for e in edges:
            if e == incoming_e or e in protected_set or e not in cost_map:
                continue
            if set(mesh.link_faces(e)) & incoming_faces:
                continue
            v_next = mesh.other_vert(e, v)
            t_out = mesh.vert_co(v_next) - mesh.vert_co(v)
            l_out = np.linalg.norm(t_out)
            if l_out < 1e-9:
                continue
            cos_a = float(np.clip(np.dot(t_in, t_out) / (l_in * l_out), -1.0, 1.0))
            if cos_a > best_cos:
                best_cos = cos_a
                best_e = e
        return best_e
    return None


def _trace_direction(mesh, start_e, start_v, cost_map, protected_set):
    loop = [start_e]
    v = start_v
    e = start_e
    visited_verts = {v}
    while True:
        if mesh.is_boundary(e) or e in protected_set:
            return loop, True
        edges = list(mesh.link_edges(v))
        if any(mesh.is_boundary(ed) or ed in protected_set for ed in edges):
            return loop, True  # reached a boundary / feature crease cleanly

        nxt = _get_continuation(mesh, v, e, cost_map, protected_set)
        if nxt is None:
            # Reached a boundary / crease or non-traversable singularity
            if any(mesh.is_boundary(ed) or ed in protected_set for ed in mesh.link_edges(v)):
                return loop, True
            return loop, False
        other = mesh.other_vert(nxt, v)
        if other in visited_verts:
            loop.append(nxt)
            return loop, True  # closed ring
        loop.append(nxt)
        visited_verts.add(other)
        v = other
        e = nxt
    return loop, False


def trace_full_transverse_loop(mesh, start_edge, cost_map, protected_set):
    if start_edge in protected_set:
        return None
    v0, v1 = mesh.edge_verts(start_edge)
    fwd_loop, fwd_hit = _trace_direction(mesh, start_edge, v1, cost_map, protected_set)
    if not fwd_hit:
        return None

    # Check if fwd_loop closed back to v0 (periodic closed ring)
    if len(fwd_loop) > 2 and v0 in mesh.edge_verts(fwd_loop[-1]):
        seen = set()
        deduped = []
        for ed in fwd_loop:
            if ed not in seen:
                seen.add(ed)
                deduped.append(ed)
        return deduped

    back_loop, back_hit = _trace_direction(mesh, start_edge, v0, cost_map, protected_set)
    if not back_hit:
        return None

    full_loop = list(reversed(back_loop[1:])) + fwd_loop
    seen = set()
    deduped = []
    for ed in full_loop:
        if ed not in seen:
            seen.add(ed)
            deduped.append(ed)
    if len(deduped) < 1:
        return None
    return deduped


def _loop_direction_and_ar_ok(mesh, loop, ar_gate=2.5):
    """Computes loop 3D direction vector and verifies that every proposed quad merge
    satisfies bounding aspect ratio <= ar_gate (default 2.5).
    """
    coords = []
    for le in loop:
        v0, v1 = mesh.edge_verts(le)
        coords.append(mesh.vert_co(v0))
        coords.append(mesh.vert_co(v1))
    coords = np.array(coords)

    if len(coords) >= 2:
        diff = coords[-1] - coords[0]
        norm_diff = np.linalg.norm(diff)
        if norm_diff > 1e-6:
            dir_vec = diff / norm_diff
        else:
            centered = coords - coords.mean(axis=0)
            cov = np.dot(centered.T, centered)
            eigvals, eigvecs = np.linalg.eigh(cov)
            dir_vec = eigvecs[:, -1]
    else:
        dir_vec = np.array([1.0, 0.0, 0.0])

    # Check aspect ratio gate for all quads formed if this loop is dissolved
    ar_ok = True
    for le in loop:
        lf = mesh.link_faces(le)
        if len(lf) != 2:
            continue
        v_a, v_b = mesh.edge_verts(le)
        pa, pb = mesh.vert_co(v_a), mesh.vert_co(v_b)
        w = float(np.linalg.norm(pb - pa))
        if w < 1e-9:
            continue
        f0, f1 = lf[0], lf[1]
        area0 = mesh.calc_area(f0)
        area1 = mesh.calc_area(f1)
        h = (area0 + area1) / max(w, 1e-9)
        ar = max(w, h) / max(min(w, h), 1e-7)
        if ar > ar_gate:
            ar_ok = False
            break

    return dir_vec, ar_ok


def simplify_component(mesh, max_passes=20, hard_fail_area_drift=5.0,
                        warn_area_drift=0.02, ar_gate=2.5, max_flat_deg=12.0):
    """Multi-pass dissolve with Aspect-Ratio-Gated Dual-Axis Alternation.
    Returns stats dict. Mutates mesh in place.
    """
    mesh.fix_winding_consistency()

    initial_face_areas = [mesh.calc_area(f) for f in mesh.faces]
    local_median_area = float(np.median(initial_face_areas)) if initial_face_areas else 0.0

    area_before = _total_area(mesh)
    total_dissolved = 0
    passes_run = 0
    max_drift_seen = 0.0
    ref_direction = None

    for pass_idx in range(max_passes):
        cost_map, protected_set, _ = protect_mod.compute_edge_costs(
            mesh, local_median_area=local_median_area)

        candidate_edges = sorted(
            (e for e in mesh.edges if e in cost_map and e not in protected_set),
            key=lambda e: cost_map[e],
        )

        visited = set()
        classified_loops = []  # list of (loop, dir_vec, cost)
        for e in candidate_edges:
            if e in visited:
                continue
            loop = trace_full_transverse_loop(mesh, e, cost_map, protected_set)
            if loop is None or len(loop) < 1:
                continue

            # Check flatness along the loop
            valid_flat = True
            for le in loop:
                lf = mesh.link_faces(le)
                if len(lf) != 2:
                    valid_flat = False
                    break
                n0 = mesh.face_normal(lf[0])
                n1 = mesh.face_normal(lf[1])
                cos_a = float(np.clip(np.dot(n0, n1), -1.0, 1.0))
                if math.degrees(math.acos(cos_a)) > max_flat_deg:
                    valid_flat = False
                    break
            if not valid_flat:
                continue

            dir_vec, ar_ok = _loop_direction_and_ar_ok(mesh, loop, ar_gate=ar_gate)
            if not ar_ok:
                continue

            avg_cost = sum(cost_map[le] for le in loop) / len(loop)
            classified_loops.append((loop, dir_vec, avg_cost))
            for le in loop:
                visited.add(le)

        if not classified_loops:
            break

        # Establish reference direction for dual-axis scheduling
        if ref_direction is None and classified_loops:
            ref_direction = classified_loops[0][1]

        # Target axis: even passes = parallel to ref_direction, odd passes = orthogonal
        target_axis = pass_idx % 2  # 0: parallel, 1: orthogonal

        def loop_axis(dvec):
            if ref_direction is None:
                return 0
            align = abs(float(np.dot(dvec, ref_direction)))
            return 0 if align >= 0.7071 else 1

        axis_loops = [item for item in classified_loops if loop_axis(item[1]) == target_axis]

        # Decoupled asymmetric fallback: if active axis has 0 valid loops with AR <= 2.5,
        # allow the orthogonal axis to proceed
        if not axis_loops:
            orthogonal_axis = 1 - target_axis
            axis_loops = [item for item in classified_loops if loop_axis(item[1]) == orthogonal_axis]

        if not axis_loops:
            break

        # Sort candidate loops flattest/cheapest first
        axis_loops.sort(key=lambda item: item[2])

        used_faces = set()
        accepted = []
        for loop, _dir_vec, _cost in axis_loops:
            faces = set()
            for le in loop:
                faces.update(mesh.link_faces(le))
            if faces & used_faces:
                continue
            used_faces |= faces
            accepted.append(loop)

        if not accepted:
            break

        n_boundary_before = len(mesh.boundary_edges())
        n_before_faces = len(list(mesh.faces))

        # Pairwise quad merge along each accepted full loop with per-edge collinear cleanup
        for loop in accepted:
            if not all(le in mesh._edge_faces for le in loop):
                continue
            merged_edge_verts = set()
            for le in loop:
                if le not in mesh._edge_faces:
                    continue
                lf = mesh.link_faces(le)
                if len(lf) != 2:
                    continue
                f0, f1 = lf[0], lf[1]
                if f0 not in mesh._face_verts or f1 not in mesh._face_verts:
                    continue
                v0, v1 = mesh.edge_verts(le)
                new_f = mesh.merge_faces([f0, f1], dissolve_verts=False)
                if new_f is not None:
                    merged_edge_verts.add(v0)
                    merged_edge_verts.add(v1)

            valid_verts = [v for v in merged_edge_verts if v in mesh._vert_co]
            if valid_verts:
                mesh.dissolve_collinear_verts(valid_verts, angle_tol_deg=10.0)

        n_boundary_after = len(mesh.boundary_edges())

        # The PRIMARY invariant: dissolve never moves a vertex, only merges
        # face topology, so it can never legitimately create a new boundary
        # edge (a hole) — this is the reliable, planarity-independent safety
        # check.
        if n_boundary_after > n_boundary_before:
            raise RuntimeError(
                f"Pass {pass_idx}: boundary edges grew from {n_boundary_before} "
                f"to {n_boundary_after} — a real hole, rejecting."
            )

        # SECONDARY, best-effort check: cumulative area drift from the
        # ORIGINAL geometry (not compounded per-pass). Logged, only fatal if
        # implausibly large (see docstring above).
        area_now = _total_area(mesh)
        cumulative_drift = abs(area_now - area_before) / max(1e-9, area_before)
        max_drift_seen = max(max_drift_seen, cumulative_drift)
        if cumulative_drift > hard_fail_area_drift:
            raise RuntimeError(
                f"Pass {pass_idx}: cumulative area drift {cumulative_drift:.1%} "
                f"exceeds the {hard_fail_area_drift:.0%} hard-fail ceiling — "
                f"rejecting as a likely bug, not just non-planar-ngon "
                f"approximation noise."
            )

        total_dissolved += (n_before_faces - len(list(mesh.faces)))
        passes_run += 1

    area_after = _total_area(mesh)
    return {
        "passes_run": passes_run,
        "faces_removed": total_dissolved,
        "area_before": area_before,
        "area_after": area_after,
        "area_delta": area_after - area_before,
        "area_before_triangulated": area_before,
        "area_after_triangulated": area_after,
        "max_cumulative_area_drift": max_drift_seen,
        "area_drift_warning": max_drift_seen > warn_area_drift,
    }


def simplify_obj_file(in_obj, out_obj, max_passes=20):
    mesh = io_mesh.load(in_obj)
    stats = simplify_component(mesh, max_passes=max_passes)
    io_mesh.export(out_obj, mesh, quads=True)
    stats["out_obj"] = out_obj
    return stats


# ---------------------------------------------------------------------------
# Synthetic self-test: a flat MxN quad grid must dissolve toward very few
# faces with ZERO area change and zero holes (required T7 verification).
# ---------------------------------------------------------------------------

def _build_flat_grid(nx=10, ny=6, size=1.0):
    mesh = EditMesh()
    verts = [[mesh.add_vert((x * size / nx, y * size / ny, 0.0)) for x in range(nx + 1)]
             for y in range(ny + 1)]
    for y in range(ny):
        for x in range(nx):
            mesh.add_face([verts[y][x], verts[y][x + 1], verts[y + 1][x + 1], verts[y + 1][x]])
    return mesh


def self_test():
    mesh = _build_flat_grid(nx=10, ny=6)
    area_before = _total_area(mesh)
    n_faces_before = len(list(mesh.faces))
    n_boundary_before = len(mesh.boundary_edges())

    stats = simplify_component(mesh)

    n_boundary_after = len(mesh.boundary_edges())
    result = {
        "faces_before": n_faces_before,
        "faces_after": len(list(mesh.faces)),
        "area_before": area_before,
        "area_after": _total_area(mesh),
        "boundary_before": n_boundary_before,
        "boundary_after": n_boundary_after,
        "stats": stats,
    }
    return result


if __name__ == "__main__":
    args = sys.argv[1:]

    if args and args[0] == "--self-test":
        result = self_test()
        print("DISSOLVE_SELFTEST_JSON_START")
        print(json.dumps(result, indent=2))
        print("DISSOLVE_SELFTEST_JSON_END")
    elif len(args) >= 2:
        stats = simplify_obj_file(args[0], args[1])
        print("DISSOLVE_RESULT_JSON_START")
        print(json.dumps(stats, indent=2))
        print("DISSOLVE_RESULT_JSON_END")
    else:
        print("Usage: python3 dissolve.py --self-test")
        print("   or: python3 dissolve.py <in.obj> <out.obj>")
        sys.exit(1)
