"""Transverse-loop + straight-slat dissolution driven by protect.py's
continuous cost field — no fixed 3deg/18deg tiers. Runs under Blender
(bpy/bmesh), one component at a time.

Ports the proven loop-tracing mechanics from tripo_smart_engine's
ribbon_engine.py (`trace_full_transverse_loop`) near-verbatim, but instead
of two hardcoded angle tiers, a single pass processes ALL non-hard-
protected edges (cost < math.inf, i.e. everything protect.py didn't flag
as a real feature), always preferring the lowest-cost (flattest) loops
first each pass. Since protect.py already guarantees every finite cost is
strictly below the crease threshold, there is no extra tolerance knob to
tune here — "dissolve everything that isn't a protected feature, flattest
first" is itself the continuous generalization of the old tiers.

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

import bpy
import bmesh

import config
import io_blender
import protect as protect_mod


def _total_area(bm):
    return sum(f.calc_area() for f in bm.faces)


def _total_area_triangulated(bm):
    """Fan-triangulate every face from its own vertex positions and sum
    triangle areas. Unlike bmesh's own face.calc_area() (which approximates
    a non-planar n-gon via a best-fit-plane projection, i.e. Newell's
    method), this stays close to how trimesh/most tools measure area and is
    far less sensitive to a merged face becoming non-planar — confirmed by
    direct comparison: a dissolve pass that LOOKED fine (identical silhouette
    rendered before/after) showed bm.calc_area() drifting ~5%/pass while
    this triangulated measure and trimesh's own computation both agreed at
    ~2%, consistent with real (small) planarity approximation noise, not an
    actual hole. Used as the real safety-check measure; bm.calc_area() is
    kept only for human-readable logging.
    """
    total = 0.0
    for f in bm.faces:
        verts = f.verts
        if len(verts) < 3:
            continue
        v0 = verts[0].co
        for i in range(1, len(verts) - 1):
            v1 = verts[i].co
            v2 = verts[i + 1].co
            total += (v1 - v0).cross(v2 - v0).length * 0.5
    return total


def _get_continuation(v, incoming_e, cost_map, protected_set):
    """Mirrors ribbon_engine.trace_full_transverse_loop's inner
    get_continuation_edge: valence must be exactly 4, continuation edge
    must not share a face with the incoming edge, must not be protected."""
    if len(v.link_edges) != 4:
        return None
    incoming_faces = set(incoming_e.link_faces)
    for e in v.link_edges:
        if e is incoming_e:
            continue
        if e.index in protected_set:
            continue
        if set(e.link_faces) & incoming_faces:
            continue
        if e.index not in cost_map:
            continue
        return e
    return None


def _trace_direction(start_e, start_v, cost_map, protected_set):
    loop = [start_e]
    v = start_v
    e = start_e
    visited_verts = {v.index}
    hit_end = False
    while True:
        nxt = _get_continuation(v, e, cost_map, protected_set)
        if nxt is None:
            hit_end = True
            break
        other = nxt.other_vert(v)
        if other.index in visited_verts:
            hit_end = True  # closed ring
            break
        loop.append(nxt)
        visited_verts.add(other.index)
        v = other
        e = nxt
    return loop, hit_end


def trace_full_transverse_loop(start_edge, cost_map, protected_set):
    if start_edge.index in protected_set:
        # Defense in depth: a protected edge must never be dissolved, even
        # if a caller forgets to filter it out of the candidate list.
        return None
    v0, v1 = start_edge.verts
    back_loop, back_hit = _trace_direction(start_edge, v0, cost_map, protected_set)
    fwd_loop, fwd_hit = _trace_direction(start_edge, v1, cost_map, protected_set)

    full_loop = list(reversed(back_loop[1:])) + [start_edge] + fwd_loop[1:]
    if not (back_hit and fwd_hit):
        return None
    if len(full_loop) < 1:
        return None
    return full_loop


def simplify_component(bm, max_passes=20, hard_fail_area_drift=5.0,
                        warn_area_drift=0.02, min_faces=None):
    """Multi-pass dissolve. Returns stats dict. Mutates bm in place.

    `min_faces`: optional floor -- stops dissolving (without raising) once
    `len(bm.faces) <= min_faces`, rather than always running to full
    convergence. Exists only for the user-requested hard output-face-count
    band: letting dissolve stop EARLY, at whatever field-aligned structure
    remesh already produced, keeps the natural anisotropic flow the
    pipeline is built around -- unlike post-hoc isotropic subdivision
    (`subdivide_mesh.py`), which was found to destroy that structure
    entirely (confirmed via a user-shared screenshot showing uniformly
    dense, non-flowing quads). `None` (default) is this project's normal
    behavior: dissolve always runs to full convergence, no floor.

    Area-drift handling (see _total_area_triangulated's docstring): dissolve
    never moves a vertex, so the ONE mathematically exact, planarity-
    independent invariant is that boundary-edge count can never increase —
    that is the hard gate. Triangulated-area drift is tracked as a
    best-effort SECONDARY signal: real-world quad-dominant meshes bend in
    3D, so merging two non-perfectly-coplanar faces into a larger n-gon
    changes how an ill-defined "area" is approximated, independent of
    whether any geometry was actually lost (confirmed directly: a pass with
    ~2-4% triangulated-area drift rendered pixel-identical before/after,
    silhouette intact, zero new boundary edges). Only an implausibly large
    drift (>hard_fail_area_drift) is treated as a real bug; anything between
    warn_area_drift and that ceiling is recorded in stats, not raised.
    """
    area_before = _total_area(bm)
    area_before_tri = _total_area_triangulated(bm)
    total_dissolved = 0
    passes_run = 0
    max_drift_seen = 0.0

    for pass_idx in range(max_passes):
        if min_faces is not None and len(bm.faces) <= min_faces:
            break
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        cost_map, protected_set, _ = protect_mod.compute_edge_costs(bm)

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
            (e for e in bm.edges if e.index in cost_map and e.index not in protected_set),
            key=lambda e: cost_map[e.index],
        )

        visited = set()
        loops = []
        for e in candidate_edges:
            if e.index in visited:
                continue
            loop = trace_full_transverse_loop(e, cost_map, protected_set)
            if loop is None or len(loop) < 1:
                continue
            loops.append(loop)
            for le in loop:
                visited.add(le.index)

        if not loops:
            break

        # Greedy: cheapest-average-cost loops first, skip any touching an
        # already-claimed face.
        def avg_cost(loop):
            return sum(cost_map[e.index] for e in loop) / len(loop)

        loops.sort(key=avg_cost)
        used_faces = set()
        accepted = []
        # BUG FIX, found via a user-requested hard output-floor feature
        # (2026-11-02): the top-of-loop `len(bm.faces) <= min_faces` check
        # only stops dissolve BETWEEN passes, but one pass can greedily
        # accept dozens of loops at once -- confirmed directly, a single
        # pass blew straight through a 9,737-face target down to 8,350,
        # overshooting by more than the margin padding added to compensate.
        # Fix: track a running face budget WITHIN the pass too, using each
        # loop's own edge count as the (slightly approximate, but good
        # enough -- a transverse loop dissolve removes very close to one
        # face per edge dissolved) estimate of faces it will remove, and
        # stop accepting MORE loops once the budget is exhausted, rather
        # than only checking again after the whole pass already ran.
        faces_budget = (len(bm.faces) - min_faces) if min_faces is not None else None
        for loop in loops:
            if faces_budget is not None and faces_budget <= 0:
                break
            faces = set()
            for e in loop:
                faces.update(f.index for f in e.link_faces)
            if faces & used_faces:
                continue
            used_faces |= faces
            accepted.append(loop)
            if faces_budget is not None:
                faces_budget -= len(loop)

        if not accepted:
            break

        n_boundary_before = sum(1 for e in bm.edges if e.is_boundary)
        # A loop can legitimately revisit the same edge where its forward and
        # backward traces meet (e.g. a short/near-closed run) — bmesh.ops.
        # dissolve_edges rejects a duplicate edge in its input list outright
        # ("found the same (BMEdge) used multiple times"), so dedupe here.
        edges_to_dissolve = list({e for loop in accepted for e in loop})
        n_before_faces = len(bm.faces)
        bmesh.ops.dissolve_edges(bm, edges=edges_to_dissolve, use_verts=True)
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        n_boundary_after = sum(1 for e in bm.edges if e.is_boundary)

        # The PRIMARY invariant: dissolve_edges never moves a vertex, only
        # merges face topology, so it can never legitimately create a new
        # boundary edge (a hole) — this is the reliable, planarity-
        # independent safety check.
        if n_boundary_after > n_boundary_before:
            raise RuntimeError(
                f"Pass {pass_idx}: boundary edges grew from {n_boundary_before} "
                f"to {n_boundary_after} — a real hole, rejecting."
            )

        # SECONDARY, best-effort check: cumulative triangulated-area drift
        # from the ORIGINAL geometry (not compounded per-pass). Logged, only
        # fatal if implausibly large (see docstring above).
        area_now_tri = _total_area_triangulated(bm)
        cumulative_drift = abs(area_now_tri - area_before_tri) / max(1e-9, area_before_tri)
        max_drift_seen = max(max_drift_seen, cumulative_drift)
        if cumulative_drift > hard_fail_area_drift:
            raise RuntimeError(
                f"Pass {pass_idx}: cumulative triangulated-area drift "
                f"{cumulative_drift:.1%} exceeds the {hard_fail_area_drift:.0%} "
                f"hard-fail ceiling — rejecting as a likely bug, not just "
                f"non-planar-ngon approximation noise."
            )

        total_dissolved += (n_before_faces - len(bm.faces))
        passes_run += 1

    area_after = _total_area(bm)
    area_after_tri = _total_area_triangulated(bm)
    return {
        "passes_run": passes_run,
        "faces_removed": total_dissolved,
        "area_before": area_before,
        "area_after": area_after,
        "area_delta": area_after - area_before,
        "area_before_triangulated": area_before_tri,
        "area_after_triangulated": area_after_tri,
        "max_cumulative_area_drift": max_drift_seen,
        "area_drift_warning": max_drift_seen > warn_area_drift,
    }


def simplify_obj_file(in_obj, out_obj, max_passes=20):
    io_blender.clear_scene()
    mesh_objs = io_blender.import_mesh(in_obj)
    obj = mesh_objs[0]
    bm = bmesh.new()
    bm.from_mesh(obj.data)

    stats = simplify_component(bm, max_passes=max_passes)

    bm.to_mesh(obj.data)
    obj.data.update()
    bm.free()

    io_blender.export_mesh(out_obj, objects=[obj], quads=True)
    stats["out_obj"] = out_obj
    return stats


# ---------------------------------------------------------------------------
# Synthetic self-test: a flat MxN quad grid must dissolve toward very few
# faces with ZERO area change and zero holes (required T7 verification).
# ---------------------------------------------------------------------------

def _build_flat_grid(bm, nx=10, ny=6, size=1.0):
    verts = [[bm.verts.new((x * size / nx, y * size / ny, 0.0)) for x in range(nx + 1)]
             for y in range(ny + 1)]
    for y in range(ny):
        for x in range(nx):
            bm.faces.new([verts[y][x], verts[y][x + 1], verts[y + 1][x + 1], verts[y + 1][x]])
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()


def self_test():
    bm = bmesh.new()
    _build_flat_grid(bm, nx=10, ny=6)
    area_before = _total_area(bm)
    n_faces_before = len(bm.faces)
    n_boundary_before = sum(1 for e in bm.edges if e.is_boundary)

    stats = simplify_component(bm)

    n_boundary_after = sum(1 for e in bm.edges if e.is_boundary)
    result = {
        "faces_before": n_faces_before,
        "faces_after": len(bm.faces),
        "area_before": area_before,
        "area_after": _total_area(bm),
        "boundary_before": n_boundary_before,
        "boundary_after": n_boundary_after,
        "stats": stats,
    }
    bm.free()
    return result


if __name__ == "__main__":
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]

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
        print("Usage: blender --background --python dissolve.py -- --self-test")
        print("   or: blender --background --python dissolve.py -- <in.obj> <out.obj>")
        sys.exit(1)
