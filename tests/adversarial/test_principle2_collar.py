"""Adversarial stress harness for Principle 2: Feature Collar / Sleeve Boundary Isolation.

Tests:
1. Feature at center (distance > 3 quads) - Baseline.
2. Feature proximate to boundary (distance = 1 quad, collar k=1 and k=2).
3. Feature touching boundary (distance < 1 quad).
4. Feature in a corner (distance < 1 quad to TWO boundaries).
5. Multiple features close to each other (distance < 2k quads, overlapping collars).
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
from tests.mesh_factory import create_quad_grid


def build_panel_with_hole(grid_n=10, hole_x=5, hole_y=5, hole_size=2):
    """Creates a grid_n x grid_n quad panel where a hole of hole_size x hole_size quads
    is removed at (hole_x, hole_y).
    """
    v, f = create_quad_grid(nx=grid_n, ny=grid_n, dx=1.0, dy=1.0)
    # Filter out faces inside hole: x in [hole_x, hole_x + hole_size), y in [hole_y, hole_y + hole_size)
    remaining_faces = []
    hole_faces = []
    
    # In create_quad_grid: face (j, i) corresponds to x in [i, i+1], y in [j, j+1]
    for face_idx, face in enumerate(f):
        # find min x and min y of the face
        coords = np.array([v[vi] for vi in face])
        min_x = coords[:, 0].min()
        min_y = coords[:, 1].min()
        if (hole_x <= min_x < hole_x + hole_size) and (hole_y <= min_y < hole_y + hole_size):
            hole_faces.append(face)
        else:
            remaining_faces.append(face)
            
    mesh = EditMesh.from_arrays(v, remaining_faces)
    return mesh, v, remaining_faces


def get_k_ring_neighborhood(mesh, inner_boundary_edges, k=1):
    """Collects k-ring faces incident to the inner boundary edges."""
    collar_faces = set()
    current_verts = set()
    for e in inner_boundary_edges:
        v0, v1 = mesh.edge_verts(e)
        current_verts.add(v0)
        current_verts.add(v1)
        
    for ring in range(k):
        next_verts = set()
        for v in current_verts:
            for fid in mesh.faces:
                fverts = mesh.face_verts(fid)
                if v in fverts:
                    collar_faces.add(fid)
                    next_verts.update(fverts)
        current_verts = next_verts
    return collar_faces


def evaluate_collar_isolation(grid_n=10, hole_x=5, hole_y=5, hole_size=2, k=1, label=""):
    print(f"\n=======================================================")
    print(f"CASE: {label} (hole at ({hole_x}, {hole_y}), dist_to_boundary_x={hole_x}, dist_to_boundary_y={hole_y}, k={k})")
    print(f"=======================================================")
    mesh, v, f = build_panel_with_hole(grid_n, hole_x, hole_y, hole_size)
    
    # 1. Detect boundary edges
    b_edges = mesh.boundary_edges()
    
    # Separate outer boundary vs inner hole boundary
    # Outer boundary has vertices at x=0, x=grid_n, y=0, y=grid_n
    outer_b_edges = set()
    inner_b_edges = set()
    for e in b_edges:
        v0, v1 = mesh.edge_verts(e)
        c0 = mesh.vert_co(v0)
        c1 = mesh.vert_co(v1)
        # Outer boundary sits on grid_n bounds
        is_outer = (c0[0] in (0.0, float(grid_n)) and c1[0] in (0.0, float(grid_n))) or \
                   (c0[1] in (0.0, float(grid_n)) and c1[1] in (0.0, float(grid_n)))
        if is_outer:
            outer_b_edges.add(e)
        else:
            inner_b_edges.add(e)
            
    print(f"Mesh stats: {len(mesh.faces)} faces, {len(b_edges)} boundary edges ({len(outer_b_edges)} outer, {len(inner_b_edges)} inner)")
    
    # 2. Extract k-ring collar
    collar_faces = get_k_ring_neighborhood(mesh, inner_b_edges, k=k)
    print(f"Collar ({k}-ring) contains {len(collar_faces)} faces")
    
    # 3. Check if collar touches outer boundary
    collar_verts = set()
    for fid in collar_faces:
        collar_verts.update(mesh.face_verts(fid))
    
    touches_outer = any(mesh.edge_verts(e)[0] in collar_verts or mesh.edge_verts(e)[1] in collar_verts for e in outer_b_edges)
    print(f"Collar touches outer boundary: {touches_outer}")
    
    # 4. Remaining planar panel: Omega_outer = Faces \ Collar
    remaining_planar_faces = set(mesh.faces) - collar_faces
    print(f"Remaining planar panel has {len(remaining_planar_faces)} faces")
    
    # 5. Test planar merge on remaining planar faces
    # Does merge_faces succeed on remaining planar faces?
    # Test boundary walk on remaining faces
    boundary_edges = []
    seen = set()
    for fid in remaining_planar_faces:
        for eid in mesh.face_edges(fid):
            if eid in seen:
                continue
            seen.add(eid)
            internal = sum(1 for lf in mesh._edge_faces[eid] if lf in remaining_planar_faces)
            if internal < 2:
                boundary_edges.append(eid)
                
    loop = mesh._walk_boundary_loop(boundary_edges)
    if loop is None:
        print(f"FAIL: _walk_boundary_loop returned None! (Not disk topology or disconnected!)")
    else:
        print(f"SUCCESS: _walk_boundary_loop found single simple loop with {len(loop)} vertices.")
        
    # Attempt merge_faces
    merged_fid = mesh.merge_faces(remaining_planar_faces, dissolve_verts=False)
    if merged_fid is None:
        print(f"FAIL: merge_faces(remaining_planar_faces) REJECTED!")
    else:
        print(f"SUCCESS: merge_faces created face {merged_fid} with {len(mesh.face_verts(merged_fid))} vertices.")
        
    return {
        "touches_outer": touches_outer,
        "walk_success": (loop is not None),
        "merge_success": (merged_fid is not None),
    }


def run_all_collar_tests():
    # Case 1: Centered feature (safe baseline)
    r1 = evaluate_collar_isolation(grid_n=10, hole_x=4, hole_y=4, hole_size=2, k=1, label="Centered hole (dist=4 quads)")
    
    # Case 2: Boundary-proximate feature (1 quad from boundary, k=1)
    r2 = evaluate_collar_isolation(grid_n=10, hole_x=1, hole_y=4, hole_size=2, k=1, label="Proximate hole (dist=1 quad, k=1)")
    
    # Case 3: Boundary-proximate feature (1 quad from boundary, k=2)
    r3 = evaluate_collar_isolation(grid_n=10, hole_x=1, hole_y=4, hole_size=2, k=2, label="Proximate hole (dist=1 quad, k=2)")
    
    # Case 4: Feature touching boundary (dist=0 quads, k=1)
    r4 = evaluate_collar_isolation(grid_n=10, hole_x=0, hole_y=4, hole_size=2, k=1, label="Flush hole on boundary (dist=0 quads, k=1)")
    
    # Case 5: Feature in corner (dist=1 quad from two boundaries, k=2)
    r5 = evaluate_collar_isolation(grid_n=10, hole_x=1, hole_y=1, hole_size=2, k=2, label="Corner hole (dist=1 quad to X and Y, k=2)")


if __name__ == "__main__":
    run_all_collar_tests()
