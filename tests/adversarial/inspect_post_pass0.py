"""Diagnostic script to inspect vertex valences and loop continuation after Pass 0 dissolution."""

import os
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_DIR))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if os.path.join(_ROOT, "core") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "core"))

from editmesh import EditMesh
from tests.mesh_factory import create_quad_grid
import dissolve

def inspect_post_pass0():
    v, f = create_quad_grid(nx=4, ny=4, dx=1.0, dy=1.0)
    mesh = EditMesh.from_arrays(v, f)
    cost_map = {e: 0.0 for e in mesh.edges}
    protected_set = set(mesh.boundary_edges())
    
    # Trace loops
    loops = []
    for e in mesh.edges:
        if e in protected_set:
            continue
        fl = dissolve.trace_full_transverse_loop(mesh, e, cost_map, protected_set)
        if fl:
            loops.append(fl)
            
    print(f"Initial: {len(mesh.faces)} faces, {len(mesh.edges)} edges, {len(mesh.verts)} verts")
    print(f"Found {len(loops)} candidate loops")
    
    # Pick one horizontal loop
    # Let's see edge 4
    for i, l in enumerate(loops):
        print(f"Loop {i}: len={len(l)}, edges={l}")
        
    # Execute dissolve on loop 0
    l0 = loops[0]
    loop_verts = set()
    for le in l0:
        v0, v1 = mesh.edge_verts(le)
        loop_verts.add(v0)
        loop_verts.add(v1)
        lf = mesh.link_faces(le)
        if len(lf) == 2:
            mesh.merge_faces([lf[0], lf[1]], dissolve_verts=False)
            
    mesh.dissolve_collinear_verts([v for v in loop_verts if v in mesh._vert_co], angle_tol_deg=10.0)
    
    print(f"After Loop 0 dissolve: {len(mesh.faces)} faces, {len(mesh.edges)} edges, {len(mesh.verts)} verts")
    
    # Inspect all vertex valences
    print("\nVertex Valences after Pass 0:")
    for vid in mesh.verts:
        co = mesh.vert_co(vid)
        edges = list(mesh.link_edges(vid))
        faces = list(mesh.link_faces_for_vert(vid) if hasattr(mesh, "link_faces_for_vert") else [f for f in mesh.faces if vid in mesh.face_verts(f)])
        is_b = mesh.is_boundary_vert(vid) if hasattr(mesh, "is_boundary_vert") else any(mesh.is_boundary(e) for e in edges)
        print(f"Vert {vid} at {co}: val={len(edges)}, faces={len(faces)}, boundary={is_b}")
        
    # Try tracing transverse loops now!
    cost_map2 = {e: 0.0 for e in mesh.edges}
    protected_set2 = set(mesh.boundary_edges())
    loops_after = []
    for e in mesh.edges:
        if e in protected_set2:
            continue
        fl = dissolve.trace_full_transverse_loop(mesh, e, cost_map2, protected_set2)
        if fl:
            loops_after.append(fl)
            
    print(f"\nLoops traceable after Pass 0: {len(loops_after)}")
    for i, l in enumerate(loops_after):
        print(f"Loop {i}: len={len(l)}, edges={l}")

if __name__ == "__main__":
    inspect_post_pass0()
