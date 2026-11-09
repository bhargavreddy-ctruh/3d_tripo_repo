"""Test Principle 2 with two internal features (e.g. two knobs or two cutouts)."""

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


def test_two_holes(grid_n=12, dist_between=2, k=1):
    print(f"\n=======================================================")
    print(f"CASE: Two holes (grid={grid_n}x{grid_n}, dist_between={dist_between} quads, k={k})")
    print(f"=======================================================")
    v, f = create_quad_grid(nx=grid_n, ny=grid_n, dx=1.0, dy=1.0)
    # Hole 1 at (3, 5), size 2x2. Hole 2 at (3 + 2 + dist_between, 5), size 2x2
    h1_x, h1_y = 3, 5
    h2_x, h2_y = 3 + 2 + dist_between, 5
    hole_size = 2
    
    remaining_faces = []
    for face in f:
        coords = np.array([v[vi] for vi in face])
        min_x = coords[:, 0].min()
        min_y = coords[:, 1].min()
        in_h1 = (h1_x <= min_x < h1_x + hole_size) and (h1_y <= min_y < h1_y + hole_size)
        in_h2 = (h2_x <= min_x < h2_x + hole_size) and (h2_y <= min_y < h2_y + hole_size)
        if not (in_h1 or in_h2):
            remaining_faces.append(face)
            
    mesh = EditMesh.from_arrays(v, remaining_faces)
    b_edges = mesh.boundary_edges()
    
    # Inner boundary edges
    inner_edges = set()
    for e in b_edges:
        v0, v1 = mesh.edge_verts(e)
        c0, c1 = mesh.vert_co(v0), mesh.vert_co(v1)
        is_outer = (c0[0] in (0.0, float(grid_n)) and c1[0] in (0.0, float(grid_n))) or \
                   (c0[1] in (0.0, float(grid_n)) and c1[1] in (0.0, float(grid_n)))
        if not is_outer:
            inner_edges.add(e)
            
    # k-ring collar
    collar_faces = set()
    current_verts = set()
    for e in inner_edges:
        v0, v1 = mesh.edge_verts(e)
        current_verts.add(v0); current_verts.add(v1)
    for ring in range(k):
        next_verts = set()
        for v_id in current_verts:
            for fid in mesh.faces:
                fverts = mesh.face_verts(fid)
                if v_id in fverts:
                    collar_faces.add(fid)
                    next_verts.update(fverts)
        current_verts = next_verts
        
    remaining_planar = set(mesh.faces) - collar_faces
    print(f"Total faces: {len(mesh.faces)}, Collar faces: {len(collar_faces)}, Remaining planar faces: {len(remaining_planar)}")
    
    # Boundary walk on remaining
    boundary_edges = []
    seen = set()
    for fid in remaining_planar:
        for eid in mesh.face_edges(fid):
            if eid in seen:
                continue
            seen.add(eid)
            internal = sum(1 for lf in mesh._edge_faces[eid] if lf in remaining_planar)
            if internal < 2:
                boundary_edges.append(eid)
                
    loop = mesh._walk_boundary_loop(boundary_edges)
    print(f"_walk_boundary_loop result: {loop is not None} (boundary edges count = {len(boundary_edges)})")
    
    # Check connected components of remaining faces
    import networkx as nx
    g = nx.Graph()
    for fid in remaining_planar:
        g.add_node(fid)
    for fid in remaining_planar:
        for eid in mesh.face_edges(fid):
            for lf in mesh.link_faces(eid):
                if lf in remaining_planar and lf != fid:
                    g.add_edge(fid, lf)
    comps = list(nx.connected_components(g))
    print(f"Remaining planar faces connected components: {len(comps)}")


if __name__ == "__main__":
    test_two_holes(grid_n=12, dist_between=2, k=1)
    test_two_holes(grid_n=12, dist_between=1, k=1)
    test_two_holes(grid_n=12, dist_between=0, k=1)
