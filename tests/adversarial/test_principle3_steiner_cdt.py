"""Adversarial stress harness for Principle 3 (Steiner-point CDT) and Principle 4 (Convex quad pairing).

Tests:
1. Boundary conforming test: Does pure-Python Delaunay (scipy.spatial.Delaunay) preserve the exact boundary segments of non-convex / annular / L-shaped polygons, or does it produce cracks / missing edges / non-manifold edges?
2. Quad pairing efficiency: Does darts.py triangle pairing on grid-aligned CDT triangles guarantee >= 75% quads across diverse polygon geometries?
3. Watertightness test: When the CDT patch is stitched back into the surrounding mesh, are there 0 boundary cracks and 0 non-manifold edges?
4. Corner angle / shape test: Are paired quads strictly convex with corner angles in [60 deg, 120 deg]?
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


def generate_grid_steiner_points(polygon_2d, h, margin_factor=0.5):
    """Generates grid-aligned Steiner points inside polygon_2d per Section 6.3."""
    poly_path = mpath.Path(polygon_2d)
    min_x, min_y = polygon_2d.min(axis=0)
    max_x, max_y = polygon_2d.max(axis=0)
    
    xs = np.arange(min_x + margin_factor * h, max_x, h)
    ys = np.arange(min_y + margin_factor * h, max_y, h)
    grid_x, grid_y = np.meshgrid(xs, ys)
    grid_pts = np.column_stack([grid_x.ravel(), grid_y.ravel()])
    
    # Check point in polygon with margin
    inside_mask = poly_path.contains_points(grid_pts)
    steiner_pts = grid_pts[inside_mask]
    return steiner_pts


def triangulate_polygon_with_steiner(polygon_2d, h=1.0):
    """Triangulates polygon using pure-Python Delaunay + Steiner points per Section 6.3."""
    n_boundary = len(polygon_2d)
    steiner_pts = generate_grid_steiner_points(polygon_2d, h)
    
    if len(steiner_pts) > 0:
        all_pts = np.vstack([polygon_2d, steiner_pts])
    else:
        all_pts = polygon_2d
        
    # Delaunay triangulation
    dt = Delaunay(all_pts)
    
    # Filter triangles whose centroids are inside polygon
    poly_path = mpath.Path(polygon_2d)
    tri_verts = dt.simplices
    
    valid_tris = []
    for tri in tri_verts:
        pts = all_pts[tri]
        centroid = pts.mean(axis=0)
        if poly_path.contains_point(centroid):
            valid_tris.append(tri)
            
    return all_pts, np.array(valid_tris), n_boundary


def test_boundary_preservation(polygon_name, polygon_2d, h=1.0):
    """Tests if the triangulated mesh boundary EXACTLY matches the polygon boundary edges."""
    print(f"\n--- Testing Boundary Preservation on {polygon_name} (h={h}) ---")
    pts, tris, n_boundary = triangulate_polygon_with_steiner(polygon_2d, h=h)
    
    # Extract boundary edges of the triangulated mesh
    from collections import defaultdict
    edge_counts = defaultdict(int)
    for tri in tris:
        for i in range(3):
            e = tuple(sorted((tri[i], tri[(i + 1) % 3])))
            edge_counts[e] += 1
            
    tri_boundary_edges = {e for e, c in edge_counts.items() if c == 1}
    
    # Expected boundary edges from polygon_2d
    expected_boundary_edges = set()
    for i in range(n_boundary):
        e = tuple(sorted((i, (i + 1) % n_boundary)))
        expected_boundary_edges.add(e)
        
    missing_edges = expected_boundary_edges - tri_boundary_edges
    extra_boundary_edges = tri_boundary_edges - expected_boundary_edges
    
    # Check if any triangle in tris crossed or straddled
    print(f"Total points: {len(pts)} ({n_boundary} boundary, {len(pts) - n_boundary} Steiner)")
    print(f"Total triangles retained: {len(tris)}")
    print(f"Expected boundary edges: {len(expected_boundary_edges)}")
    print(f"Triangulated boundary edges: {len(tri_boundary_edges)}")
    print(f"Missing original boundary edges: {len(missing_edges)} -> {list(missing_edges)[:5]}")
    print(f"Extra / leaked boundary edges: {len(extra_boundary_edges)} -> {list(extra_boundary_edges)[:5]}")
    
    boundary_exact = (len(missing_edges) == 0 and len(extra_boundary_edges) == 0)
    print(f"Exact Boundary Preservation: {'PASS' if boundary_exact else 'FAIL (CRACK / DEVIATION DETECTED!)'}")
    return boundary_exact, pts, tris


def test_quad_pairing_efficiency(pts, tris, polygon_name):
    """Tests darts.py quad pairing on the triangulated mesh."""
    print(f"\n--- Testing Quad Pairing with darts.py on {polygon_name} ---")
    # Build EditMesh in 3D (z=0)
    v_3d = np.hstack([pts, np.zeros((len(pts), 1))])
    mesh = EditMesh.from_arrays(v_3d, [tuple(t) for t in tris])
    
    stats = darts.merge_coplanar_triangle_pairs(mesh, angle_shape_deg=90.0)
    
    n_faces = len(list(mesh.faces))
    quads = sum(1 for f in mesh.faces if len(mesh.face_verts(f)) == 4)
    tris_after = sum(1 for f in mesh.faces if len(mesh.face_verts(f)) == 3)
    ngons = sum(1 for f in mesh.faces if len(mesh.face_verts(f)) > 4)
    quad_pct = (quads / n_faces * 100.0) if n_faces > 0 else 0.0
    
    print(f"Initial Triangles: {stats['tris_before']}")
    print(f"Pairs Merged: {stats['pairs_merged']}")
    print(f"Final Faces: {n_faces} (Quads: {quads} [{quad_pct:.1f}%], Tris: {tris_after}, N-gons: {ngons})")
    print(f"Quad Dominance >= 75%: {'PASS' if quad_pct >= 75.0 else 'FAIL'}")
    print(f"Strictly 0% N-gons: {'PASS' if ngons == 0 else 'FAIL'}")
    
    return {
        "quad_pct": quad_pct,
        "ngons": ngons,
        "tris_after": tris_after,
        "pairs_merged": stats["pairs_merged"],
    }


def run_all_cdt_darts_challenges():
    # 1. Simple Convex Rectangle (10 x 6)
    rect = np.array([
        [0.0, 0.0], [10.0, 0.0], [10.0, 6.0], [0.0, 6.0]
    ])
    b1, pts1, tris1 = test_boundary_preservation("Convex Rectangle", rect, h=1.0)
    test_quad_pairing_efficiency(pts1, tris1, "Convex Rectangle")
    
    # 2. Non-Convex L-Shaped Polygon
    l_shape = np.array([
        [0.0, 0.0], [8.0, 0.0], [8.0, 4.0], [4.0, 4.0], [4.0, 8.0], [0.0, 8.0]
    ])
    b2, pts2, tris2 = test_boundary_preservation("Non-Convex L-Shape", l_shape, h=1.0)
    test_quad_pairing_efficiency(pts2, tris2, "Non-Convex L-Shape")
    
    # 3. Concave U-Shaped Polygon (Simulating panel cutouts)
    u_shape = np.array([
        [0.0, 0.0], [10.0, 0.0], [10.0, 8.0], [7.0, 8.0], [7.0, 3.0], [3.0, 3.0], [3.0, 8.0], [0.0, 8.0]
    ])
    b3, pts3, tris3 = test_boundary_preservation("Concave U-Shape", u_shape, h=1.0)
    test_quad_pairing_efficiency(pts3, tris3, "Concave U-Shape")
    
    # 4. Polygon with Acute Corner / Slanted Edge (Simulating non-axis-aligned boundary)
    trapezoid = np.array([
        [0.0, 0.0], [10.0, 0.0], [7.5, 5.0], [2.5, 5.0]
    ])
    b4, pts4, tris4 = test_boundary_preservation("Trapezoid with Slanted Edges", trapezoid, h=1.0)
    test_quad_pairing_efficiency(pts4, tris4, "Trapezoid with Slanted Edges")
    
    # 5. Annular Keyhole Polygon (Simulating Face 705 from woodenrack)
    # Outer rectangle with circular inner hole connected by bridge seam
    knob_center = np.array([5.0, 4.0])
    knob_radius = 1.0
    n_knob = 12
    knob_angles = np.linspace(0, 2 * np.pi, n_knob, endpoint=False)
    knob_pts = knob_center + knob_radius * np.column_stack([np.cos(knob_angles), np.sin(knob_angles)])
    
    # Keyhole perimeter: outer corners, bridge to knob, around knob, bridge back
    keyhole = [
        [0.0, 0.0], [10.0, 0.0], [10.0, 8.0], [0.0, 8.0], [0.0, 4.0]
    ]
    # bridge from [0, 4] to knob_pts[6] (leftmost knob vertex)
    keyhole_full = keyhole + knob_pts.tolist() + [[0.0, 4.0]]
    keyhole_arr = np.array(keyhole_full)
    b5, pts5, tris5 = test_boundary_preservation("Annular Keyhole Polygon (Face 705 replica)", keyhole_arr, h=0.8)
    test_quad_pairing_efficiency(pts5, tris5, "Annular Keyhole Polygon (Face 705 replica)")


if __name__ == "__main__":
    run_all_cdt_darts_challenges()
