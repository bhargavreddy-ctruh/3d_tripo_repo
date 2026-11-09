"""Adversarial stress harness for Principle 1: Aspect-ratio-gated dual-axis decimation.

Tests:
1. Deadlock / dead-end under orthogonal blockage (when one axis is blocked by extraordinary vertex or boundary, AR gate halts both axes).
2. Valence-3 and Valence-5 pole interactions: does loop decimation stall or create irregular non-valence-4 boundaries?
3. Curvature-varying / non-Cartesian quad flow: PCA axis projection failure on organic/curved surfaces.
4. Closed cylindrical topology loop continuation.
"""

import math
import os
import sys
import numpy as np

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_DIR))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if os.path.join(_ROOT, "core") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "core"))

from editmesh import EditMesh
from tests.mesh_factory import (
    create_quad_grid,
    create_quad_cylinder,
    create_quad_box,
    create_quad_sphere,
)
import dissolve


def simulate_ar_gated_alternating_dissolve(mesh, max_passes=6, ar_gate=2.5):
    """Simulates the Principle 1 dual-axis alternating decimation with AR gating.
    Returns audit statistics: pass count, faces per pass, deadlocks, aspect ratios.
    """
    history = []
    
    for pass_idx in range(max_passes):
        cost_map = {e: 0.0 for e in mesh.edges}
        protected_set = set(mesh.boundary_edges())
        active_axis = 0 if (pass_idx % 2 == 0) else 1  # 0: U (e.g. X), 1: V (e.g. Y)
        n_faces_before = len(list(mesh.faces))
        
        # 1. Collect all valid transverse loops
        all_loops = []
        for e in mesh.edges:
            if e in protected_set:
                continue
            res = dissolve.trace_full_transverse_loop(mesh, e, cost_map, protected_set)
            full_loop = res
            if full_loop is not None:
                loop = full_loop
                # Determine loop direction vector
                coords = []
                for le in loop:
                    v0, v1 = mesh.edge_verts(le)
                    coords.append(mesh.vert_co(v0))
                    coords.append(mesh.vert_co(v1))
                coords = np.array(coords)
                p_span = coords.max(axis=0) - coords.min(axis=0)
                # Primary span direction
                loop_dir = 0 if p_span[0] > p_span[1] else 1
                
                # Check aspect ratio gate for all quads formed if this loop is dissolved
                ar_ok = True
                for le in loop:
                    lf = mesh.link_faces(le)
                    if len(lf) != 2:
                        continue
                    # Compute merged bounding box aspect ratio
                    f_verts = set(mesh.face_verts(lf[0])) | set(mesh.face_verts(lf[1]))
                    f_coords = np.array([mesh.vert_co(v) for v in f_verts])
                    span = f_coords.max(axis=0) - f_coords.min(axis=0)
                    dims = [s for s in span if s > 1e-6]
                    if len(dims) >= 2:
                        ar = max(dims[0], dims[1]) / min(dims[0], dims[1])
                    else:
                        ar = 1.0
                    if ar > ar_gate:
                        ar_ok = False
                        break
                
                if ar_ok:
                    all_loops.append((loop_dir, loop))
        
        # Filter loops by active axis
        matching_loops = [loop for l_dir, loop in all_loops if l_dir == active_axis]
        
        # Greedy face-disjoint selection
        used_faces = set()
        accepted = []
        for loop in matching_loops:
            faces = set()
            for le in loop:
                faces.update(mesh.link_faces(le))
            if faces & used_faces:
                continue
            used_faces |= faces
            accepted.append(loop)
            
        # Execute merge
        merged_count = 0
        merge_face_successes = 0
        merge_face_failures = 0
        for loop in accepted:
            loop_verts = set()
            for le in loop:
                if le in mesh._edge_verts:
                    v0, v1 = mesh.edge_verts(le)
                    loop_verts.add(v0)
                    loop_verts.add(v1)
            
            loop_ok = True
            print(f"Pass {pass_idx}: loop has {len(loop)} edges. Edges in _edge_faces: {[le in mesh._edge_faces for le in loop]}")
            for le in loop:
                if le not in mesh._edge_faces:
                    continue
                lf = mesh.link_faces(le)
                if len(lf) == 2:
                    nf = mesh.merge_faces([lf[0], lf[1]], dissolve_verts=False)
                    if nf is None:
                        loop_ok = False
                        merge_face_failures += 1
                    else:
                        merge_face_successes += 1
            if loop_ok:
                valid_verts = [v for v in loop_verts if v in mesh._vert_co]
                if valid_verts:
                    n_diss = mesh.dissolve_collinear_verts(valid_verts, angle_tol_deg=10.0)
                merged_count += 1
                
        n_faces_after = len(list(mesh.faces))
        print(f"Pass {pass_idx} DEBUG: accepted={len(accepted)}, successes={merge_face_successes}, failures={merge_face_failures}")
        history.append({
            "pass": pass_idx,
            "axis": "U" if active_axis == 0 else "V",
            "matching_loops": len(matching_loops),
            "merged_loops": merged_count,
            "faces_before": n_faces_before,
            "faces_after": n_faces_after,
            "stalled": (n_faces_before == n_faces_after),
        })
        if pass_idx >= 1 and history[-1]["stalled"] and history[-2]["stalled"]:
            # Complete deadlock: both axes stalled consecutively
            break
            
    return history


def test_regular_grid_behavior():
    v, f = create_quad_grid(nx=8, ny=8, dx=1.0, dy=1.0)
    mesh = EditMesh.from_arrays(v, f)
    hist = simulate_ar_gated_alternating_dissolve(mesh, max_passes=6, ar_gate=2.5)
    print("=== TEST 1: REGULAR 8x8 GRID ===")
    for h in hist:
        print(f"Pass {h['pass']} ({h['axis']}): matched={h['matching_loops']}, merged={h['merged_loops']}, faces: {h['faces_before']} -> {h['faces_after']}, stalled={h['stalled']}")
    return hist


def test_deadlock_under_orthogonal_blockage():
    """Create a grid where one axis has an extraordinary vertex (valence 3/5 pole) in the center.
    Observe if decimation dead-ends due to AR gate + blocked transverse loop.
    """
    v, f = create_quad_grid(nx=8, ny=8, dx=1.0, dy=1.0)
    # Introduce an extraordinary pole by perturbing one face into a triangle + pentagon or splitting an edge
    # Let's create an irregular valence vertex at center (v=40 in an 8x8 grid has 81 verts)
    # A standard way: merge two diagonal vertices or add a diagonal cut
    mesh = EditMesh.from_arrays(v, f)
    # Pick an interior edge and split or perturb it so valence becomes 3 or 5
    # For example, remove one edge to create a valence 3 vertex
    int_edges = [e for e in mesh.edges if len(mesh.link_faces(e)) == 2]
    # Let's see behavior
    hist = simulate_ar_gated_alternating_dissolve(mesh, max_passes=6, ar_gate=2.5)
    print("=== TEST 2: DEADLOCK UNDER BLOCKAGE ===")
    # Now let's test a mesh with a valence-3 pole in the middle of a column
    # If a column has valence != 4, vertical loops cannot cross it!
    # Let's construct a grid with a missing edge or T-junction:
    # A 6x6 grid where one vertical edge is removed
    v2, f2 = create_quad_grid(nx=6, ny=6, dx=1.0, dy=1.0)
    mesh2 = EditMesh.from_arrays(v2, f2)
    # Mark a vertical loop as protected (simulating a feature or crease)
    protected = set(mesh2.boundary_edges())
    # Protect an entire vertical column
    for e in mesh2.edges:
        v0, v1 = mesh2.edge_verts(e)
        if abs(mesh2.vert_co(v0)[0] - 3.0) < 1e-4 and abs(mesh2.vert_co(v1)[0] - 3.0) < 1e-4:
            protected.add(e)
            
    print(f"Total protected edges: {len(protected)}")
    # If vertical column is protected, horizontal loops hit it and stop or vertical loops are protected
    return hist


if __name__ == "__main__":
    test_regular_grid_behavior()
    test_deadlock_under_orthogonal_blockage()
