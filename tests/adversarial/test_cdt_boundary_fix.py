"""Empirical test of boundary conforming Delaunay:
Can edge subdivision (conforming Delaunay) or edge recovery eliminate boundary cracks?
"""

import math
import os
import sys
import numpy as np
from scipy.spatial import Delaunay
import matplotlib.path as mpath

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_DIR))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if os.path.join(_ROOT, "core") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "core"))

from editmesh import EditMesh
import darts


def subdivide_boundary(polygon_2d, h):
    """Subdivide polygon boundary edges so that every boundary edge has length <= h."""
    new_boundary = []
    n = len(polygon_2d)
    for i in range(n):
        p0 = polygon_2d[i]
        p1 = polygon_2d[(i + 1) % n]
        edge_vec = p1 - p0
        edge_len = np.linalg.norm(edge_vec)
        num_sub = max(1, int(np.ceil(edge_len / h)))
        for s in range(num_sub):
            t = s / num_sub
            new_boundary.append(p0 + t * edge_vec)
    return np.array(new_boundary)


def test_conforming_boundary(polygon_name, polygon_2d, h=1.0):
    print(f"\n--- Testing Conforming Boundary on {polygon_name} (h={h}) ---")
    sub_boundary = subdivide_boundary(polygon_2d, h=h)
    n_boundary = len(sub_boundary)
    
    # Steiner points
    poly_path = mpath.Path(polygon_2d)
    min_x, min_y = polygon_2d.min(axis=0)
    max_x, max_y = polygon_2d.max(axis=0)
    xs = np.arange(min_x + 0.5 * h, max_x, h)
    ys = np.arange(min_y + 0.5 * h, max_y, h)
    gx, gy = np.meshgrid(xs, ys)
    grid_pts = np.column_stack([gx.ravel(), gy.ravel()])
    steiner_pts = grid_pts[poly_path.contains_points(grid_pts)]
    
    all_pts = np.vstack([sub_boundary, steiner_pts])
    dt = Delaunay(all_pts)
    
    valid_tris = []
    for tri in dt.simplices:
        pts = all_pts[tri]
        if poly_path.contains_point(pts.mean(axis=0)):
            valid_tris.append(tri)
            
    # Check boundary edges
    from collections import defaultdict
    edge_counts = defaultdict(int)
    for tri in valid_tris:
        for i in range(3):
            e = tuple(sorted((tri[i], tri[(i + 1) % 3])))
            edge_counts[e] += 1
            
    tri_boundary = {e for e, c in edge_counts.items() if c == 1}
    expected_boundary = {tuple(sorted((i, (i + 1) % n_boundary))) for i in range(n_boundary)}
    
    missing = expected_boundary - tri_boundary
    leaked = tri_boundary - expected_boundary
    
    print(f"Subdivided boundary vertices: {n_boundary}")
    print(f"Missing boundary edges: {len(missing)}")
    print(f"Leaked boundary edges: {len(leaked)}")
    print(f"Boundary Conforming Status: {'PASS (WATERTIGHT)' if len(missing) == 0 and len(leaked) == 0 else 'FAIL (CRACK)'}")
    
    # Test quad pairing
    v_3d = np.hstack([all_pts, np.zeros((len(all_pts), 1))])
    mesh = EditMesh.from_arrays(v_3d, [tuple(t) for t in valid_tris])
    stats = darts.merge_coplanar_triangle_pairs(mesh, angle_shape_deg=90.0)
    n_faces = len(list(mesh.faces))
    quads = sum(1 for f in mesh.faces if len(mesh.face_verts(f)) == 4)
    quad_pct = (quads / n_faces * 100.0) if n_faces > 0 else 0.0
    print(f"Quad Dominance: {quad_pct:.1f}% ({quads} quads, {n_faces - quads} tris)")
    return len(missing) == 0 and len(leaked) == 0


if __name__ == "__main__":
    l_shape = np.array([[0.0, 0.0], [8.0, 0.0], [8.0, 4.0], [4.0, 4.0], [4.0, 8.0], [0.0, 8.0]])
    test_conforming_boundary("Non-Convex L-Shape", l_shape, h=1.0)
    u_shape = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 8.0], [7.0, 8.0], [7.0, 3.0], [3.0, 3.0], [3.0, 8.0], [0.0, 8.0]])
    test_conforming_boundary("Concave U-Shape", u_shape, h=1.0)
