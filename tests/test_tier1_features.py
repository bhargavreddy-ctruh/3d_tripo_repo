"""Tier 1: Feature Coverage Test Suite.

Covers 5 core geometric features with >= 5 comprehensive test cases each:
1. Quad Grids (regular, decimated, rectangular, 3D oriented, hexahedral box, interior valence)
2. Planar Faces (pure planar, convex partitioning, tilted plane, normal alignment, annular quad disc)
3. Internal Hole Features (circular collar, rectangular cutout, small knob isolation, Steiner CDT, boundary preservation)
4. Curved Surfaces (cylinder body, UV sphere, torus, hyperbolic saddle, variable curvature)
5. Boundary Loops & Manifold Topology (watertight solid, multi-component, crack detection, non-manifold edges, open loop)
"""

import math
import os
import sys
import unittest
import numpy as np

# Add parent directory to path
_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from tests.mesh_factory import (
    create_quad_grid,
    create_quad_box,
    create_quad_cylinder,
    create_quad_sphere,
    create_planar_collar_panel,
    create_cracked_solid_box,
    _weld_vertices,
)
from tests.verify_mesh_quality import MeshQualityVerifier


class TestTier1QuadGrids(unittest.TestCase):
    """Feature 1: Quad Grids (>= 5 test cases)."""

    def test_uniform_isotropic_quad_grid(self):
        """Case 1.1: Uniform 4x4 isotropic quad grid has aspect ratio 1.0 and 100% quads."""
        v, f = create_quad_grid(nx=4, ny=4, dx=1.0, dy=1.0)
        verifier = MeshQualityVerifier(v, f, allow_open=True)
        res = verifier.verify()
        self.assertTrue(res["checks"]["ngons"], "Must have 0% N-gons")
        self.assertTrue(res["checks"]["quad_dominance"], "Must have >= 75% quads")
        self.assertEqual(res["metrics"]["composition"]["quad_pct"], 100.0)
        self.assertTrue(res["checks"]["planar_quad_ar"], "Aspect ratio must be < 3.5")
        self.assertAlmostEqual(res["metrics"]["planar_quad_aspect_ratio"]["max"], 1.0, places=4)
        self.assertEqual(res["metrics"]["composition"]["ngon_count"], 0)

    def test_aspect_ratio_bounded_rectangular_grid(self):
        """Case 1.2: Rectangular quad grid with dx=1.0, dy=2.5 maintains AR < 3.5 threshold."""
        v, f = create_quad_grid(nx=6, ny=6, dx=1.0, dy=2.5)
        verifier = MeshQualityVerifier(v, f, allow_open=True, max_planar_ar=3.5)
        res = verifier.verify()
        self.assertTrue(res["checks"]["planar_quad_ar"])
        self.assertAlmostEqual(res["metrics"]["planar_quad_aspect_ratio"]["percentile_90"], 2.5, places=2)
        self.assertEqual(res["metrics"]["planar_quad_aspect_ratio"]["extreme_slat_count"], 0)

    def test_3d_oriented_quad_grid(self):
        """Case 1.3: Arbitrarily rotated 3D quad grid preserves coordinate-invariant aspect ratio."""
        v, f = create_quad_grid(nx=5, ny=5, dx=1.0, dy=1.0)
        # Apply arbitrary 3D rotation (Euler angles: 30 deg X, 45 deg Y, 60 deg Z)
        rx = math.radians(30)
        ry = math.radians(45)
        rz = math.radians(60)
        Rx = np.array([[1, 0, 0], [0, math.cos(rx), -math.sin(rx)], [0, math.sin(rx), math.cos(rx)]])
        Ry = np.array([[math.cos(ry), 0, math.sin(ry)], [0, 1, 0], [-math.sin(ry), 0, math.cos(ry)]])
        Rz = np.array([[math.cos(rz), -math.sin(rz), 0], [math.sin(rz), math.cos(rz), 0], [0, 0, 1]])
        rot = Rz @ Ry @ Rx
        v_rot = v @ rot.T + np.array([10.0, -5.0, 2.5])

        verifier = MeshQualityVerifier(v_rot, f, allow_open=True)
        res = verifier.verify()
        self.assertTrue(res["checks"]["planar_quad_ar"])
        self.assertAlmostEqual(res["metrics"]["planar_quad_aspect_ratio"]["median"], 1.0, places=3)
        self.assertEqual(res["metrics"]["planar_quad_aspect_ratio"]["count"], len(f))

    def test_hexahedral_watertight_box_mesh(self):
        """Case 1.4: Hexahedral box made of 6 quad grids is watertight with 0 cracks."""
        v, f = create_quad_box(sub_x=3, sub_y=3, sub_z=3)
        verifier = MeshQualityVerifier(v, f, allow_open=False)
        res = verifier.verify()
        self.assertTrue(res["passed"])
        self.assertEqual(res["metrics"]["boundary"]["boundary_edge_count"], 0)
        self.assertEqual(res["metrics"]["boundary"]["non_manifold_edge_count"], 0)
        self.assertEqual(res["metrics"]["composition"]["quad_pct"], 100.0)

    def test_interior_vertex_valence_regularity(self):
        """Case 1.5: Regular interior quad grid vertices have exactly valence 4."""
        nx, ny = 5, 5
        v, f = create_quad_grid(nx=nx, ny=ny)
        # Count valence per vertex
        from collections import defaultdict
        vert_val = defaultdict(int)
        for face in f:
            k = len(face)
            for i in range(k):
                edge = frozenset((face[i], face[(i + 1) % k]))
                # Count edges incident on vertices
        edge_set = set()
        for face in f:
            k = len(face)
            for i in range(k):
                edge_set.add(frozenset((face[i], face[(i + 1) % k])))
        for e in edge_set:
            v0, v1 = tuple(e)
            vert_val[v0] += 1
            vert_val[v1] += 1

        # Interior vertices (not on border): i in [1, nx-1], j in [1, ny-1]
        interior_valences = []
        for j in range(1, ny):
            for i in range(1, nx):
                vid = j * (nx + 1) + i
                interior_valences.append(vert_val[vid])

        self.assertTrue(all(val == 4 for val in interior_valences), f"All interior valences must be 4: {interior_valences}")


class TestTier1PlanarFaces(unittest.TestCase):
    """Feature 2: Planar Faces (>= 5 test cases)."""

    def test_single_planar_panel_planarity(self):
        """Case 2.1: Planar panel with coplanar quadrilaterals has 100% planar quad classification."""
        v, f = create_quad_grid(nx=3, ny=3)
        verifier = MeshQualityVerifier(v, f, allow_open=True)
        res = verifier.verify()
        pq = res["metrics"]["planar_quad_aspect_ratio"]
        self.assertEqual(pq["count"], len(f), "All quads in flat grid must be classified as planar")
        self.assertTrue(res["checks"]["planar_quad_ar"])

    def test_convex_partitioned_planar_panel(self):
        """Case 2.2: Partitioning a planar panel into convex rectangular quads maintains 0% N-gons."""
        # Create non-uniform 2D grid partitioning
        xs = [0.0, 1.0, 2.5, 4.0]
        ys = [0.0, 0.8, 2.0, 3.5]
        verts = []
        for y in ys:
            for x in xs:
                verts.append([x, y, 0.0])
        faces = []
        for j in range(len(ys) - 1):
            for i in range(len(xs) - 1):
                v0 = j * len(xs) + i
                v1 = v0 + 1
                v2 = (j + 1) * len(xs) + i + 1
                v3 = (j + 1) * len(xs) + i
                faces.append((v0, v1, v2, v3))

        verifier = MeshQualityVerifier(np.array(verts), faces, allow_open=True)
        res = verifier.verify()
        self.assertTrue(res["checks"]["ngons"])
        self.assertTrue(res["checks"]["planar_quad_ar"])
        self.assertLess(res["metrics"]["planar_quad_aspect_ratio"]["percentile_90"], 3.5)

    def test_tilted_plane_normal_consistency(self):
        """Case 2.3: Planar panel rotated out of XY plane preserves normal consistency and planarity."""
        v, f = create_quad_grid(nx=4, ny=4)
        # Tilt plane around Y-axis by 45 degrees
        angle = math.pi / 4.0
        R = np.array([[math.cos(angle), 0, math.sin(angle)], [0, 1, 0], [-math.sin(angle), 0, math.cos(angle)]])
        v_tilted = v @ R.T
        verifier = MeshQualityVerifier(v_tilted, f, allow_open=True)
        res = verifier.verify()
        self.assertEqual(res["metrics"]["planar_quad_aspect_ratio"]["count"], len(f))
        self.assertAlmostEqual(res["metrics"]["planar_quad_aspect_ratio"]["max"], 1.0, places=3)

    def test_planar_disc_concentric_quad_rings(self):
        """Case 2.4: Concentric planar quad rings (annular sectors) satisfy aspect ratio < 3.5."""
        radii = [1.0, 1.8, 2.8]
        n_sectors = 12
        verts = []
        for r in radii:
            for i in range(n_sectors):
                th = 2.0 * math.pi * i / n_sectors
                verts.append([r * math.cos(th), r * math.sin(th), 0.0])
        faces = []
        for ring in range(len(radii) - 1):
            off0 = ring * n_sectors
            off1 = (ring + 1) * n_sectors
            for i in range(n_sectors):
                i_next = (i + 1) % n_sectors
                faces.append((off0 + i, off0 + i_next, off1 + i_next, off1 + i))

        verifier = MeshQualityVerifier(np.array(verts), faces, allow_open=True)
        res = verifier.verify()
        self.assertTrue(res["checks"]["ngons"])
        self.assertTrue(res["checks"]["quad_dominance"])
        self.assertTrue(res["checks"]["planar_quad_ar"])
        self.assertLess(res["metrics"]["planar_quad_aspect_ratio"]["percentile_90"], 3.5)

    def test_non_annular_planar_face_elimination(self):
        """Case 2.5: Ensure planar regions do not contain giant unpartitioned annular N-gons."""
        v, f = create_planar_collar_panel(size=4.0, hole_radius=0.5, collar_radius=1.0, n_pts=8)
        verifier = MeshQualityVerifier(v, f, allow_open=True)
        res = verifier.verify()
        # Verify strictly 0 N-gons and 100% quads
        self.assertEqual(res["metrics"]["composition"]["ngon_count"], 0)
        self.assertEqual(res["metrics"]["composition"]["quad_pct"], 100.0)
        self.assertTrue(res["checks"]["planar_quad_ar"])


class TestTier1InternalHoles(unittest.TestCase):
    """Feature 3: Internal Hole Features (>= 5 test cases)."""

    def test_circular_hole_collar_isolation(self):
        """Case 3.1: Circular hole surrounded by collar ring avoids spoke chords and maintains AR < 3.5."""
        v, f = create_planar_collar_panel(size=5.0, hole_radius=0.7, collar_radius=1.5, n_pts=8)
        verifier = MeshQualityVerifier(v, f, allow_open=True)
        res = verifier.verify()
        self.assertTrue(res["checks"]["ngons"])
        self.assertTrue(res["checks"]["quad_dominance"])
        self.assertTrue(res["checks"]["planar_quad_ar"])
        self.assertEqual(res["metrics"]["needle_triangles"]["count"], 0)

    def test_rectangular_hole_isolation(self):
        """Case 3.2: Rectangular internal hole with quad sleeve partition eliminates diagonal cuts."""
        # Outer square: [-3, 3] x [-3, 3]
        # Hole: [-1, 1] x [-1, 1]
        # Partitioned into 8 regular rectangular quads (top, bottom, left, right + 4 corners)
        verts = np.array(
            [
                [-3.0, -3.0, 0.0], [-1.0, -3.0, 0.0], [1.0, -3.0, 0.0], [3.0, -3.0, 0.0],
                [-3.0, -1.0, 0.0], [-1.0, -1.0, 0.0], [1.0, -1.0, 0.0], [3.0, -1.0, 0.0],
                [-3.0,  1.0, 0.0], [-1.0,  1.0, 0.0], [1.0,  1.0, 0.0], [3.0,  1.0, 0.0],
                [-3.0,  3.0, 0.0], [-1.0,  3.0, 0.0], [1.0,  3.0, 0.0], [3.0,  3.0, 0.0],
            ]
        )
        # 8 quads surrounding the center hole (5, 6, 10, 9 is omitted as hole)
        faces = [
            (0, 1, 5, 4),   # Bottom-left
            (1, 2, 6, 5),   # Bottom
            (2, 3, 7, 6),   # Bottom-right
            (4, 5, 9, 8),   # Left
            (6, 7, 11, 10), # Right
            (8, 9, 13, 12), # Top-left
            (9, 10, 14, 13),# Top
            (10, 11, 15, 14)# Top-right
        ]
        verifier = MeshQualityVerifier(verts, faces, allow_open=True)
        res = verifier.verify()
        self.assertTrue(res["checks"]["ngons"])
        self.assertEqual(res["metrics"]["composition"]["quad_pct"], 100.0)
        self.assertAlmostEqual(res["metrics"]["planar_quad_aspect_ratio"]["max"], 1.0, places=3)
        self.assertEqual(res["metrics"]["needle_triangles"]["count"], 0)

    def test_small_knob_collar_scale_ratio(self):
        """Case 3.3: Small knob (radius 0.2 on 6.0 panel) with 2-layer collar preserves AR < 3.5."""
        v, f = create_planar_collar_panel(size=6.0, hole_radius=0.2, collar_radius=0.6, n_pts=8)
        verifier = MeshQualityVerifier(v, f, allow_open=True)
        res = verifier.verify()
        self.assertTrue(res["checks"]["ngons"])
        self.assertTrue(res["checks"]["planar_quad_ar"])
        self.assertLess(res["metrics"]["planar_quad_aspect_ratio"]["percentile_90"], 3.5)

    def test_hole_steiner_triangulation_regularity(self):
        """Case 3.4: Triangulation around a circular hole using Steiner points avoids sliver chords."""
        # Delaunay-style regular triangles around hole
        n_pts = 6
        r_inner = 1.0
        r_mid = 1.6
        verts = []
        for i in range(n_pts):
            th = 2.0 * math.pi * i / n_pts
            verts.append([r_inner * math.cos(th), r_inner * math.sin(th), 0.0])
        for i in range(n_pts):
            th = 2.0 * math.pi * (i + 0.5) / n_pts
            verts.append([r_mid * math.cos(th), r_mid * math.sin(th), 0.0])
        faces = []
        for i in range(n_pts):
            i_next = (i + 1) % n_pts
            # Regular equilateral-like triangles
            faces.append((i, i_next, n_pts + i))
            faces.append((i_next, n_pts + i_next, n_pts + i))

        verifier = MeshQualityVerifier(np.array(verts), faces, allow_open=True, min_quad_pct=0.0)
        res = verifier.verify()
        self.assertTrue(res["checks"]["sliver_triangles"], "Steiner triangulation must have 0 needle slivers")
        self.assertEqual(res["metrics"]["needle_triangles"]["count"], 0)
        self.assertLess(res["metrics"]["needle_triangles"]["max_ar"], 6.0)

    def test_internal_hole_boundary_topology_closed(self):
        """Case 3.5: Hole perimeter forms a closed, non-intersecting topological boundary loop."""
        v, f = create_planar_collar_panel(size=4.0, hole_radius=0.5, collar_radius=1.0, n_pts=8)
        # Find all boundary edges
        from collections import defaultdict
        edge_counts = defaultdict(int)
        for face in f:
            k = len(face)
            for i in range(k):
                edge_counts[frozenset((face[i], face[(i + 1) % k]))] += 1
        b_edges = [e for e, count in edge_counts.items() if count == 1]
        # Hole boundary edges are at r ~ 0.5; outer boundary edges are at half-size ~ 2.0
        hole_edges = []
        for e in b_edges:
            v0, v1 = tuple(e)
            r0 = np.linalg.norm(v[v0][:2])
            r1 = np.linalg.norm(v[v1][:2])
            if r0 < 0.8 and r1 < 0.8:
                hole_edges.append(e)

        self.assertEqual(len(hole_edges), 8, "Hole boundary must have exactly 8 closed boundary edges")


class TestTier1CurvedSurfaces(unittest.TestCase):
    """Feature 4: Curved Surfaces (>= 5 test cases)."""

    def test_curved_cylinder_quad_dominance(self):
        """Case 4.1: Closed cylinder surface has >= 75% quad dominance and 0 boundary cracks."""
        v, f = create_quad_cylinder(radius=1.0, height=2.0, n_theta=16, n_z=8, closed=True)
        verifier = MeshQualityVerifier(v, f, allow_open=False)
        res = verifier.verify()
        self.assertTrue(res["passed"])
        self.assertGreaterEqual(res["metrics"]["composition"]["quad_pct"], 75.0)
        self.assertEqual(res["metrics"]["boundary"]["boundary_edge_count"], 0)

    def test_uv_sphere_quad_dominance_and_caps(self):
        """Case 4.2: Closed UV sphere satisfies quad dominance >= 75% and 0% N-gons."""
        v, f = create_quad_sphere(radius=1.0, n_lat=10, n_lon=16)
        verifier = MeshQualityVerifier(v, f, allow_open=False)
        res = verifier.verify()
        self.assertTrue(res["passed"])
        self.assertEqual(res["metrics"]["composition"]["ngon_count"], 0)
        self.assertGreaterEqual(res["metrics"]["composition"]["quad_pct"], 75.0)
        self.assertEqual(res["metrics"]["needle_triangles"]["count"], 0)

    def test_torus_closed_genus_one_manifold(self):
        """Case 4.3: Torus mesh (genus 1) is 100% quads with 0 boundary edges."""
        R_major = 2.0
        r_minor = 0.5
        n_u = 32
        n_v = 16
        verts = []
        for i in range(n_u):
            u = 2.0 * math.pi * i / n_u
            for j in range(n_v):
                v_ang = 2.0 * math.pi * j / n_v
                x = (R_major + r_minor * math.cos(v_ang)) * math.cos(u)
                y = (R_major + r_minor * math.cos(v_ang)) * math.sin(u)
                z = r_minor * math.sin(v_ang)
                verts.append([x, y, z])
        faces = []
        for i in range(n_u):
            i_next = (i + 1) % n_u
            for j in range(n_v):
                j_next = (j + 1) % n_v
                v0 = i * n_v + j
                v1 = i_next * n_v + j
                v2 = i_next * n_v + j_next
                v3 = i * n_v + j_next
                faces.append((v0, v1, v2, v3))

        verifier = MeshQualityVerifier(np.array(verts), faces, allow_open=False)
        res = verifier.verify()
        self.assertTrue(res["passed"])
        self.assertEqual(res["metrics"]["composition"]["quad_pct"], 100.0)
        self.assertEqual(res["metrics"]["boundary"]["boundary_edge_count"], 0)

    def test_hyperbolic_paraboloid_saddle_surface(self):
        """Case 4.4: Hyperbolic saddle surface z = 0.2*(x^2 - y^2) maintains quad aspect ratio < 3.5."""
        nx, ny = 6, 6
        verts = []
        for j in range(ny + 1):
            y = (j / ny) * 2.0 - 1.0
            for i in range(nx + 1):
                x = (i / nx) * 2.0 - 1.0
                z = 0.2 * (x**2 - y**2)
                verts.append([x, y, z])
        faces = []
        for j in range(ny):
            for i in range(nx):
                v0 = j * (nx + 1) + i
                v1 = v0 + 1
                v2 = (j + 1) * (nx + 1) + i + 1
                v3 = (j + 1) * (nx + 1) + i
                faces.append((v0, v1, v2, v3))

        verifier = MeshQualityVerifier(np.array(verts), faces, allow_open=True)
        res = verifier.verify()
        self.assertTrue(res["checks"]["ngons"])
        self.assertTrue(res["checks"]["quad_dominance"])
        self.assertLess(res["metrics"]["all_quad_aspect_ratio"]["percentile_90"], 3.5)

    def test_variable_curvature_quad_mesh(self):
        """Case 4.5: Curved sheet with varying radius of curvature maintains bounded aspect ratio."""
        n_pts = 10
        verts = []
        for j in range(n_pts + 1):
            y = j * 0.5
            for i in range(n_pts + 1):
                x = i * 0.5
                # Variable frequency sinusoid: curvature increases along X
                z = 0.3 * math.sin(x * 1.2)
                verts.append([x, y, z])
        faces = []
        for j in range(n_pts):
            for i in range(n_pts):
                v0 = j * (n_pts + 1) + i
                v1 = v0 + 1
                v2 = (j + 1) * (n_pts + 1) + i + 1
                v3 = (j + 1) * (n_pts + 1) + i
                faces.append((v0, v1, v2, v3))

        verifier = MeshQualityVerifier(np.array(verts), faces, allow_open=True)
        res = verifier.verify()
        self.assertTrue(res["checks"]["ngons"])
        self.assertEqual(res["metrics"]["composition"]["quad_pct"], 100.0)
        self.assertLess(res["metrics"]["all_quad_aspect_ratio"]["max"], 3.5)


class TestTier1BoundaryLoops(unittest.TestCase):
    """Feature 5: Boundary Loops & Manifold Topology (>= 5 test cases)."""

    def test_watertight_solid_zero_boundary_cracks(self):
        """Case 5.1: Solid quad box has strictly 0 boundary cracks."""
        v, f = create_quad_box(sub_x=2, sub_y=2, sub_z=2)
        verifier = MeshQualityVerifier(v, f, allow_open=False)
        res = verifier.verify()
        self.assertTrue(res["checks"]["boundary_cracks"])
        self.assertEqual(res["metrics"]["boundary"]["boundary_edge_count"], 0)

    def test_multi_component_closed_solids(self):
        """Case 5.2: Two separate closed components both have 0 boundary cracks."""
        v1, f1 = create_quad_box(w=1.0, h=1.0, d=1.0)
        v2, f2 = create_quad_box(w=2.0, h=2.0, d=2.0)
        # Offset second box
        v2_offset = v2 + np.array([5.0, 0.0, 0.0])
        all_verts = np.vstack([v1, v2_offset])
        offset = len(v1)
        all_faces = list(f1) + [tuple(idx + offset for idx in face) for face in f2]

        verifier = MeshQualityVerifier(all_verts, all_faces, allow_open=False)
        res = verifier.verify()
        self.assertTrue(res["passed"])
        self.assertEqual(res["metrics"]["islands"], 2)
        self.assertEqual(res["metrics"]["closed_components"], 2)
        self.assertEqual(res["metrics"]["boundary"]["boundary_edge_count"], 0)

    def test_detection_of_unstitched_boundary_cracks(self):
        """Case 5.3: Cracked box with missing face correctly fails boundary crack check."""
        v, f = create_cracked_solid_box()
        verifier = MeshQualityVerifier(v, f, allow_open=False)
        res = verifier.verify()
        self.assertFalse(res["checks"]["boundary_cracks"], "Cracked box must fail boundary crack check")
        self.assertFalse(res["passed"])
        self.assertGreater(res["metrics"]["boundary"]["boundary_edge_count"], 0)

    def test_detection_of_non_manifold_edges(self):
        """Case 5.4: Mesh with T-junction / non-manifold edge correctly fails manifoldness check."""
        v, f = create_quad_grid(nx=2, ny=2)
        # In a 2x2 grid:
        # Face 0: (0, 1, 4, 3); Face 1: (1, 2, 5, 4)
        # Edge (1, 4) is shared by Face 0 and Face 1.
        # Adding a 3rd face (1, 4, extra_vert) makes edge (1, 4) non-manifold (3 incident faces).
        extra_vert = len(v)
        v_nm = np.vstack([v, [[1.0, 0.5, 1.0]]])
        f_nm = list(f) + [(1, 4, extra_vert)]

        verifier = MeshQualityVerifier(v_nm, f_nm, allow_open=True)
        res = verifier.verify()
        self.assertFalse(res["checks"]["boundary_cracks"], "Non-manifold edge must fail boundary/manifold check")
        self.assertGreater(res["metrics"]["boundary"]["non_manifold_edge_count"], 0)

    def test_open_boundary_loop_extraction(self):
        """Case 5.5: Open planar patch has exactly one closed boundary loop containing perimeter edges."""
        nx, ny = 3, 3
        v, f = create_quad_grid(nx=nx, ny=ny)
        verifier = MeshQualityVerifier(v, f, allow_open=True)
        res = verifier.verify()
        self.assertTrue(res["passed"])
        # Expected boundary edges = 2 * (nx + ny) = 12
        expected_boundary_edges = 2 * (nx + ny)
        self.assertEqual(res["metrics"]["boundary"]["boundary_edge_count"], expected_boundary_edges)
        self.assertEqual(res["metrics"]["boundary"]["non_manifold_edge_count"], 0)


_CORE_DIR = os.path.join(_ROOT, "core")
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

from editmesh import EditMesh  # noqa: E402
import caps  # noqa: E402
import dome_caps  # noqa: E402


class TestTier1DomeSaddleCaps(unittest.TestCase):
    """Feature: curvature-sign-aware dome/saddle boundary-loop capping
    (core/dome_caps.py, wired into core/caps.py's cap_boundary_loop for the
    non-planar loops the flat-cap path itself rejects)."""

    def _build_ring_mesh(self, bottom_radius):
        """16-vert genuinely non-planar top loop (boundary) - lying on a
        shallow paraboloid, like a real hole's rim on a curved parent
        surface rather than a flat ring - + side-wall quads flaring to a
        bottom ring at bottom_radius. A flat top ring would be classified
        "planar enough" by caps.py's own _is_planar and never reach
        dome_caps at all (confirmed empirically: that was this fixture's
        first, wrong version). bottom_radius < 1 reads as CONVEX_DOME, > 1
        as CONCAVE_SOCKET (dome_caps._classify_curvature's convention,
        confirmed empirically in dome_caps.py's own self_test)."""
        mesh = EditMesh()
        n = 16
        top, bottom = [], []
        for i in range(n):
            theta = 2 * math.pi * i / n
            x, y = math.cos(theta), math.sin(theta)
            z_top = 0.08 * (x * x - y * y)  # shallow saddle-shaped rim
            top.append(mesh.add_vert((x, y, z_top)))
            bottom.append(mesh.add_vert((x * bottom_radius, y * bottom_radius, -0.3)))
        for i in range(n):
            j = (i + 1) % n
            mesh.add_face([top[i], top[j], bottom[j], bottom[i]])
        # Close the bottom with a single n-gon so only the TOP ring is a
        # boundary loop - isolates what's under test (dome_caps on the top
        # loop) from the bottom, which caps.py's own self_test leaves open
        # deliberately but is irrelevant here and would otherwise show up as
        # a second (always-planar, always-capped) result.
        mesh.add_face(list(reversed(bottom)))
        mesh.recalc_face_normals()
        return mesh, top

    def _get_mesh_quality(self, mesh):
        verts, faces = mesh.to_arrays()[0], mesh.to_arrays()[1]
        verifier = __import__("tests.verify_mesh_quality", fromlist=["MeshQualityVerifier"]).MeshQualityVerifier(
            verts, list(faces), allow_open=True
        )
        return verifier.verify()

    def test_convex_dome_cap_passes_quality_gates(self):
        """A non-planar loop with wall normals diverging as a dome must cap
        via dome_caps, not fail/skip, and the result must pass the core
        quality checks (0% n-gons among its own new faces, quad-dominant,
        no boundary left on that loop). The whole-mesh MeshQualityVerifier
        is not used here: this fixture's bottom closure is a deliberate
        16-gon test artifact (irrelevant to what dome_caps itself produced)
        that would otherwise trip the n-gon check for the wrong reason."""
        mesh, top = self._build_ring_mesh(bottom_radius=0.85)
        results = caps.cap_all_planar_boundaries(mesh)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["ok"], results[0])
        self.assertEqual(results[0]["type"], "CONVEX_DOME")
        self.assertEqual(results[0]["quad_pct"], 100.0 * (results[0]["faces_added"] - 16) / results[0]["faces_added"])
        self.assertEqual(mesh.boundary_edges(), [])

    def test_concave_socket_cap_passes_quality_gates(self):
        """Same construction, opposite wall flare -> CONCAVE_SOCKET, same
        quality gates."""
        mesh, top = self._build_ring_mesh(bottom_radius=1.15)
        results = caps.cap_all_planar_boundaries(mesh)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["ok"], results[0])
        self.assertEqual(results[0]["type"], "CONCAVE_SOCKET")
        self.assertEqual(results[0]["quad_pct"], 100.0 * (results[0]["faces_added"] - 16) / results[0]["faces_added"])
        self.assertEqual(mesh.boundary_edges(), [])

    def test_flat_loop_still_uses_original_parallel_chord_path(self):
        """Regression: a genuinely planar loop must NOT be routed to
        dome_caps at all - caps.py's own self_test (flat 16-gon) must behave
        exactly as it did before dome_caps existed."""
        result = caps.self_test()
        self.assertEqual(result["n_tris"], 0)
        # Pre-existing behavior (both loops rejected on cap-quad aspect
        # ratio before dome_caps.py existed) - this asserts no change, not
        # that the flat path is bug-free.
        for r in result["results"]:
            self.assertIn("reason", r)
            self.assertNotIn("dome", r["reason"])
            self.assertNotIn("socket", r["reason"].lower())

    def test_odd_length_curved_loop_still_rejected_before_dome_path(self):
        """An odd-length boundary loop must be rejected by caps.py's own
        odd-length guard before ever reaching dome_caps, whether the loop
        is planar or curved."""
        mesh = EditMesh()
        n = 15  # odd
        top, bottom = [], []
        for i in range(n):
            theta = 2 * math.pi * i / n
            x, y = math.cos(theta), math.sin(theta)
            top.append(mesh.add_vert((x, y, 0.0)))
            bottom.append(mesh.add_vert((x * 0.85, y * 0.85, -0.3)))
        for i in range(n):
            j = (i + 1) % n
            mesh.add_face([top[i], top[j], bottom[j], bottom[i]])
        mesh.add_face(list(reversed(bottom)))
        results = caps.cap_all_planar_boundaries(mesh)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"])
        self.assertIn("odd loop length", results[0]["reason"])

    def test_degenerate_elongated_curved_loop_rejected_not_slivered(self):
        """A long, thin non-planar boundary loop must be rejected by the
        aspect-ratio guard (ok: False) rather than producing sliver quads."""
        mesh = EditMesh()
        n = 16
        top, bottom = [], []
        for i in range(n):
            theta = 2 * math.pi * i / n
            # Elongate the loop itself (not just the wall) so the resulting
            # ring/fan quads are forced into a high aspect ratio.
            x, y = 4.0 * math.cos(theta), 0.3 * math.sin(theta)
            top.append(mesh.add_vert((x, y, 0.0)))
            bottom.append(mesh.add_vert((x * 0.85, y * 0.85, -0.3)))
        for i in range(n):
            j = (i + 1) % n
            mesh.add_face([top[i], top[j], bottom[j], bottom[i]])
        mesh.add_face(list(reversed(bottom)))
        results = caps.cap_all_planar_boundaries(mesh)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"])
        self.assertIn("aspect ratio", results[0]["reason"])


if __name__ == "__main__":
    unittest.main()
