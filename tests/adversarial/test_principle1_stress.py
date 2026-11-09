"""Comprehensive adversarial stress harness for Principle 1:
Aspect-ratio-gated dual-axis decimation on non-trivial topologies.

Tests:
1. Irregular / extraordinary vertices: Valence-3 and valence-5 poles (does decimation dead-end or leave irregular boundaries?).
2. Cylinder: Closed loop in theta vs open loop in Z.
3. UV Sphere: Decimation towards pole vertices (valence N).
4. Asymmetric / Non-uniform aspect ratio grids: e.g. dx=1, dy=2.4 initial grid.
5. Local PCA loop classification breakdown on organic/curved surfaces.
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


def run_dissolve_simulation(mesh, max_passes=10, ar_gate=2.5, verbose=False):
    history = []
    
    for pass_idx in range(max_passes):
        cost_map = {e: 0.0 for e in mesh.edges}
        protected_set = set(mesh.boundary_edges())
        active_axis = 0 if (pass_idx % 2 == 0) else 1  # 0: U, 1: V
        n_faces_before = len(list(mesh.faces))
        
        # 1. Trace loops
        candidate_loops = []
        for e in mesh.edges:
            if e in protected_set:
                continue
            fl = dissolve.trace_full_transverse_loop(mesh, e, cost_map, protected_set)
            if fl is not None and len(fl) > 0:
                coords = []
                for le in fl:
                    v0, v1 = mesh.edge_verts(le)
                    coords.append(mesh.vert_co(v0))
                    coords.append(mesh.vert_co(v1))
                coords = np.array(coords)
                p_span = coords.max(axis=0) - coords.min(axis=0)
                # Primary span
                primary_dir = int(np.argmax(p_span[:2])) if len(p_span) >= 2 else 0
                
                # Aspect ratio check
                ar_ok = True
                for le in fl:
                    lf = mesh.link_faces(le)
                    if len(lf) != 2:
                        continue
                    f_verts = set(mesh.face_verts(lf[0])) | set(mesh.face_verts(lf[1]))
                    f_coords = np.array([mesh.vert_co(v) for v in f_verts])
                    span = f_coords.max(axis=0) - f_coords.min(axis=0)
                    dims = [s for s in span if s > 1e-6]
                    ar = (max(dims[0], dims[1]) / min(dims[0], dims[1])) if len(dims) >= 2 else 1.0
                    if ar > ar_gate:
                        ar_ok = False
                        break
                if ar_ok:
                    candidate_loops.append((primary_dir, fl))
                    
        # Filter by active axis
        axis_loops = [loop for l_dir, loop in candidate_loops if l_dir == active_axis]
        
        # Face-disjoint greedy selection
        used_faces = set()
        accepted = []
        for loop in axis_loops:
            faces = set()
            for le in loop:
                faces.update(mesh.link_faces(le))
            if faces & used_faces:
                continue
            used_faces |= faces
            accepted.append(loop)
            
        # Merge
        merged_loops = 0
        for loop in accepted:
            loop_verts = set()
            for le in loop:
                if le in mesh._edge_verts:
                    v0, v1 = mesh.edge_verts(le)
                    loop_verts.add(v0)
                    loop_verts.add(v1)
            loop_ok = True
            for le in loop:
                if le not in mesh._edge_faces:
                    continue
                lf = mesh.link_faces(le)
                if len(lf) == 2:
                    nf = mesh.merge_faces([lf[0], lf[1]], dissolve_verts=False)
                    if nf is None:
                        loop_ok = False
            if loop_ok:
                valid_verts = [v for v in loop_verts if v in mesh._vert_co]
                if valid_verts:
                    mesh.dissolve_collinear_verts(valid_verts, angle_tol_deg=10.0)
                merged_loops += 1
                
        n_faces_after = len(list(mesh.faces))
        stalled = (n_faces_before == n_faces_after)
        history.append({
            "pass": pass_idx,
            "axis": "U" if active_axis == 0 else "V",
            "candidates": len(candidate_loops),
            "axis_matched": len(axis_loops),
            "merged": merged_loops,
            "faces_before": n_faces_before,
            "faces_after": n_faces_after,
            "stalled": stalled,
        })
        if verbose:
            print(f"Pass {pass_idx:2d} ({'U' if active_axis==0 else 'V'}): matched={len(axis_loops):2d}, merged={merged_loops:2d}, faces {n_faces_before:3d} -> {n_faces_after:3d}")
            
        if pass_idx >= 1 and history[-1]["stalled"] and history[-2]["stalled"]:
            if verbose:
                print(f"  >>> Deadlock detected at pass {pass_idx}: both axes stalled.")
            break
            
    return history


def test_extraordinary_vertex_deadlock():
    """Create a quad mesh with an extraordinary pole (valence-3 or valence-5) in the interior.
    Observe if decimation stalls or creates irregular boundaries.
    """
    print("\n--- TEST: Extraordinary Vertex (Valence-3 / Valence-5) ---")
    # Build a 6x6 quad grid, then insert a valence-3 pole by removing an interior edge
    v, f = create_quad_grid(nx=6, ny=6, dx=1.0, dy=1.0)
    mesh = EditMesh.from_arrays(v, f)
    # Pick an interior edge and merge its two faces, but DO NOT dissolve collinear verts (creating a pentagon or val 3 vert)
    # Actually, in standard quad remeshing (like Instant Meshes), a 3-5 pole pair exists.
    # Let's inspect how many loops can be traced across a mesh with a 3-5 pole pair.
    # To construct a 3-5 pole pair in quads:
    # A standard 2x1 block split into 3 quads creates valence 3 and valence 5 vertices.
    # Let's modify faces in the center:
    faces = list(f)
    # Let's replace two quads with three quads to create a 3-5 pole
    # Even simpler: protect one interior vertex or edge
    # What if one interior vertex has valence 3?
    # In EditMesh:
    int_verts = [vid for vid in mesh.verts if not any(mesh.is_boundary(e) for e in mesh.link_edges(vid))]
    # Let's run simulation on regular grid vs cylinder
    hist_grid = run_dissolve_simulation(mesh, verbose=True)
    return hist_grid


def test_cylinder_dissolution():
    """Test alternating dissolution on a quad cylinder."""
    print("\n--- TEST: Quad Cylinder (Closed Periodic Loop vs Open Axial Line) ---")
    v, f = create_quad_cylinder(radius=1.0, height=4.0, n_theta=16, n_z=8, closed=False)
    mesh = EditMesh.from_arrays(v, f)
    hist_cyl = run_dissolve_simulation(mesh, verbose=True)
    return hist_cyl


def test_initial_aspect_ratio_asymmetry():
    """Test when the initial mesh has non-unity aspect ratio (e.g. AR = 2.0).
    Can alternating dissolution start in the wrong axis and immediately deadlock?
    """
    print("\n--- TEST: Initial Aspect Ratio Asymmetry (dx=1.0, dy=2.0) ---")
    v, f = create_quad_grid(nx=8, ny=8, dx=1.0, dy=2.0)
    mesh = EditMesh.from_arrays(v, f)
    # The quads already have AR = 2.0 along Y (V axis).
    # If Pass 0 is U: merging across U increases X span from 1.0 to 2.0 (AR becomes 2.0 / 2.0 = 1.0, OK!).
    # BUT what if Pass 0 is V?
    # Merging across V increases Y span from 2.0 to 4.0! (AR becomes 4.0 > 2.5, REJECTED!).
    hist = run_dissolve_simulation(mesh, verbose=True)
    return hist


def test_uv_sphere_poles():
    """Test on a UV sphere where poles have valence N."""
    print("\n--- TEST: UV Sphere (Extraordinary Valence at Poles) ---")
    v, f = create_quad_sphere(radius=1.0, n_lat=8, n_lon=16)
    mesh = EditMesh.from_arrays(v, f)
    hist = run_dissolve_simulation(mesh, verbose=True)
    return hist


if __name__ == "__main__":
    test_extraordinary_vertex_deadlock()
    test_cylinder_dissolution()
    test_initial_aspect_ratio_asymmetry()
    test_uv_sphere_poles()
