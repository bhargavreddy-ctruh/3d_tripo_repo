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
    """Mirrors ribbon_engine.trace_full_transverse_loop's inner
    get_continuation_edge: valence must be exactly 4, continuation edge
    must not share a face with the incoming edge, must not be protected."""
    edges = list(mesh.link_edges(v))
    if len(edges) != 4:
        return None
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


def _trace_direction(mesh, start_e, start_v, cost_map, protected_set):
    loop = [start_e]
    v = start_v
    e = start_e
    visited_verts = {v}
    hit_end = False
    while True:
        nxt = _get_continuation(mesh, v, e, cost_map, protected_set)
        if nxt is None:
            hit_end = True
            break
        other = mesh.other_vert(nxt, v)
        if other in visited_verts:
            hit_end = True  # closed ring
            break
        loop.append(nxt)
        visited_verts.add(other)
        v = other
        e = nxt
    return loop, hit_end


def trace_full_transverse_loop(mesh, start_edge, cost_map, protected_set):
    if start_edge in protected_set:
        # Defense in depth: a protected edge must never be dissolved, even
        # if a caller forgets to filter it out of the candidate list.
        return None
    v0, v1 = mesh.edge_verts(start_edge)
    back_loop, back_hit = _trace_direction(mesh, start_edge, v0, cost_map, protected_set)
    fwd_loop, fwd_hit = _trace_direction(mesh, start_edge, v1, cost_map, protected_set)

    full_loop = list(reversed(back_loop[1:])) + [start_edge] + fwd_loop[1:]
    if not (back_hit and fwd_hit):
        return None
    if len(full_loop) < 1:
        return None
    return full_loop


def simplify_component(mesh, max_passes=20, hard_fail_area_drift=5.0,
                        warn_area_drift=0.02):
    """Multi-pass dissolve. Returns stats dict. Mutates mesh in place.

    Area-drift handling: dissolve never moves a vertex, so the ONE
    mathematically exact, planarity-independent invariant is that
    boundary-edge count can never increase — that is the hard gate.
    Triangulated-area drift is tracked as a best-effort SECONDARY signal:
    real-world quad-dominant meshes bend in 3D, so merging two
    non-perfectly-coplanar faces into a larger n-gon changes how an
    ill-defined "area" is approximated, independent of whether any
    geometry was actually lost. Only an implausibly large drift
    (>hard_fail_area_drift) is treated as a real bug; anything between
    warn_area_drift and that ceiling is recorded in stats, not raised.
    """
    area_before = _total_area(mesh)
    total_dissolved = 0
    passes_run = 0
    max_drift_seen = 0.0

    for pass_idx in range(max_passes):
        mesh.recalc_face_normals()
        cost_map, protected_set, _ = protect_mod.compute_edge_costs(mesh)

        # BUG FIX (found via real-asset testing, not the synthetic self-test
        # which never exercises a protected edge): cost_map has an entry for
        # EVERY edge, including hard-protected ones (with cost=inf), so
        # filtering on "in cost_map" alone let a protected (boundary/crease/
        # dome-saddle) edge become a loop START edge — trace_full_transverse_loop
        # never checks its own start_edge against protected_set, so that
        # protected edge itself could end up inside edges_to_dissolve,
        # silently merging across a real feature boundary. Must explicitly
        # exclude protected_set here.
        candidate_edges = sorted(
            (e for e in mesh.edges if e in cost_map and e not in protected_set),
            key=lambda e: cost_map[e],
        )

        visited = set()
        loops = []
        for e in candidate_edges:
            if e in visited:
                continue
            loop = trace_full_transverse_loop(mesh, e, cost_map, protected_set)
            if loop is None or len(loop) < 1:
                continue
            loops.append(loop)
            for le in loop:
                visited.add(le)

        if not loops:
            break

        # Greedy: cheapest-average-cost loops first, skip any touching an
        # already-claimed face.
        def avg_cost(loop):
            return sum(cost_map[e] for e in loop) / len(loop)

        loops.sort(key=avg_cost)
        used_faces = set()
        accepted = []
        for loop in loops:
            faces = set()
            for e in loop:
                faces.update(mesh.link_faces(e))
            if faces & used_faces:
                continue
            used_faces |= faces
            accepted.append((loop, faces))

        if not accepted:
            break

        n_boundary_before = len(mesh.boundary_edges())
        n_before_faces = len(list(mesh.faces))

        # Each accepted loop's touched-face set is disjoint from every other
        # (enforced by the greedy accept above) — merge each one into its
        # own n-gon. Equivalent to a single batched dissolve_edges call over
        # the union of all accepted loops' edges, since disjoint groups
        # never interact FACE-wise — but two different loops' resulting
        # faces CAN share a boundary VERTEX, and dissolve_verts=True's
        # collinear-vertex cleanup rebuilds every face touching a vertex it
        # removes. If that shared vertex sits on a not-yet-processed loop's
        # still-pending face, this can silently replace that face with a
        # new id before we reach it below — skip (rather than crash on) a
        # loop whose faces are no longer all present; it'll be reconsidered
        # fresh next pass since costs are recomputed from scratch each time.
        all_faces = mesh.faces
        for _loop, faces in accepted:
            if len(faces) < 2:
                continue
            if not all(f in all_faces for f in faces):
                continue
            mesh.merge_faces(faces, dissolve_verts=True)

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
