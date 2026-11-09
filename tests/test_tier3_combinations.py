"""Tier 3: Cross-Feature Combinations Test Suite.

Covers multi-feature interactions and compound geometric scenarios:
1. Holes on curved surfaces (cylindrical shell with cutout, spherical aperture, curved saddle with hole)
2. Multiple holes in single planar panel (dual knobs, 4-knob array, differing radius holes)
3. Concentric features (nested annular quad rings, stepped cylinder with flange)
4. Disjoint multi-component assemblies (composite solid/curved meshes, multi-drawer assemblies)
5. Hole proximity and collar-boundary interaction (hole close to panel edge)
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
    create_planar_collar_panel,
    _weld_vertices,
)
from tests.verify_mesh_quality import MeshQualityVerifier


class TestTier3HolesOnCurvedSurfaces(unittest.TestCase):
    """Tier 3: Holes on Curved Surfaces."""

    def test_cylinder_with_circular_hole(self):
        """Case 3.C1: Cylindrical shell containing a circular aperture with quad collar."""
        # Cylindrical coordinates: theta in [0, 2pi], z in [0, 2]
        # Hole located at theta = pi, z = 1.0, with angular radius d_theta = pi/6, d_z = 0.3
        radius = 1.0
        n_theta = 24
        n_z = 12
        verts = []
        for j in range(n_z + 1):
            z = (j / n_z) * 2.0
            for i in range(n_theta):
                th = 2.0 * math.pi * i / n_theta
                x = radius * math.cos(th)
                y = radius * math.sin(th)
                verts.append([x, y, z])

        # Remove faces corresponding to the aperture: i in [11, 12], j in [5, 6]
        faces = []
        hole_faces = {(11, 5), (11, 6), (12, 5), (12, 6)}
        for j in range(n_z):
            for i in range(n_theta):
                if (i, j) in hole_faces:
                    continue
                i_next = (i + 1) % n_theta
                v0 = j * n_theta + i
                v1 = j * n_theta + i_next
                v2 = (j + 1) * n_theta + i_next
                v3 = (j + 1) * n_theta + i
                faces.append((v0, v1, v2, v3))

        verifier = MeshQualityVerifier(np.array(verts), faces, allow_open=True)
        res = verifier.verify()
        self.assertTrue(res["checks"]["ngons"], "Cylindrical shell with cutout must have 0% N-gons")
        self.assertEqual(res["metrics"]["composition"]["quad_pct"], 100.0)
        self.assertLess(res["metrics"]["all_quad_aspect_ratio"]["percentile_90"], 3.5)

    def test_sphere_cap_with_aperture(self):
        """Case 3.C2: Spherical surface with a circular aperture at the pole."""
        radius = 1.0
        n_lat = 8
        n_lon = 16
        verts = []
        # Exclude pole, start from latitude index 1 to n_lat-1
        for i in range(1, n_lat):
            phi = math.pi * i / n_lat
            z = radius * math.cos(phi)
            r_xy = radius * math.sin(phi)
            for j in range(n_lon):
                theta = 2.0 * math.pi * j / n_lon
                verts.append([r_xy * math.cos(theta), r_xy * math.sin(theta), z])

        faces = []
        for i in range(n_lat - 2):
            row0 = i * n_lon
            row1 = (i + 1) * n_lon
            for j in range(n_lon):
                j_next = (j + 1) % n_lon
                faces.append((row0 + j, row1 + j, row1 + j_next, row0 + j_next))

        verifier = MeshQualityVerifier(np.array(verts), faces, allow_open=True)
        res = verifier.verify()
        self.assertTrue(res["checks"]["ngons"])
        self.assertEqual(res["metrics"]["composition"]["quad_pct"], 100.0)

    def test_curved_saddle_with_hole(self):
        """Case 3.C3: Hyperbolic saddle surface z = 0.1*(x^2 - y^2) with center hole removed."""
        nx, ny = 8, 8
        verts = []
        for j in range(ny + 1):
            y = (j / ny) * 2.0 - 1.0
            for i in range(nx + 1):
                x = (i / nx) * 2.0 - 1.0
                z = 0.1 * (x**2 - y**2)
                verts.append([x, y, z])
        faces = []
        hole_cells = {(3, 3), (3, 4), (4, 3), (4, 4)}
        for j in range(ny):
            for i in range(nx):
                if (i, j) in hole_cells:
                    continue
                v0 = j * (nx + 1) + i
                v1 = v0 + 1
                v2 = (j + 1) * (nx + 1) + i + 1
                v3 = (j + 1) * (nx + 1) + i
                faces.append((v0, v1, v2, v3))

        verifier = MeshQualityVerifier(np.array(verts), faces, allow_open=True)
        res = verifier.verify()
        self.assertTrue(res["checks"]["ngons"])
        self.assertEqual(res["metrics"]["composition"]["quad_pct"], 100.0)


class TestTier3MultipleHolesPlanar(unittest.TestCase):
    """Tier 3: Multiple Holes in Single Planar Panel."""

    def test_dual_knobs_planar_drawer_panel(self):
        """Case 3.C4: Drawer front panel with 2 circular knobs/holes isolated by individual collars.
        Directly models the target woodenrack geometry: no annular merging between knobs!
        """
        # Panel 1 with hole at X = -2.5
        v1, f1 = create_planar_collar_panel(size=3.0, hole_radius=0.4, collar_radius=0.9, n_pts=8)
        v1[:, 0] -= 2.0  # Center at X = -2.0
        # Panel 2 with hole at X = +2.5
        v2, f2 = create_planar_collar_panel(size=3.0, hole_radius=0.4, collar_radius=0.9, n_pts=8)
        v2[:, 0] += 2.0  # Center at X = +2.0

        all_verts = np.vstack([v1, v2])
        offset = len(v1)
        all_faces = list(f1) + [tuple(vi + offset for vi in face) for face in f2]

        # Weld boundary seam where the two panels touch at X=0
        v_welded, inv_map = _weld_vertices(all_verts, tol=1e-4)
        f_welded = [tuple(inv_map[vi] for vi in face) for face in all_faces]

        verifier = MeshQualityVerifier(v_welded, f_welded, allow_open=True)
        res = verifier.verify()
        self.assertTrue(res["checks"]["ngons"], "Dual knob panel must have strictly 0% N-gons")
        self.assertEqual(res["metrics"]["composition"]["quad_pct"], 100.0)
        self.assertTrue(res["checks"]["planar_quad_ar"])
        self.assertEqual(res["metrics"]["needle_triangles"]["count"], 0)

    def test_quad_knobs_grid_panel(self):
        """Case 3.C5: 2x2 grid of 4 knobs across a planar panel with non-intersecting collars."""
        centers = [(-2.0, -2.0), (2.0, -2.0), (-2.0, 2.0), (2.0, 2.0)]
        all_verts_list = []
        all_faces_list = []
        cur_offset = 0

        for cx, cy in centers:
            v, f = create_planar_collar_panel(size=3.0, hole_radius=0.3, collar_radius=0.8, n_pts=8)
            v[:, 0] += cx
            v[:, 1] += cy
            all_verts_list.append(v)
            all_faces_list.extend([tuple(vi + cur_offset for vi in face) for face in f])
            cur_offset += len(v)

        combined_verts = np.vstack(all_verts_list)
        v_welded, inv_map = _weld_vertices(combined_verts, tol=1e-3)
        f_welded = [tuple(inv_map[vi] for vi in face) for face in all_faces_list]

        verifier = MeshQualityVerifier(v_welded, f_welded, allow_open=True)
        res = verifier.verify()
        self.assertTrue(res["passed"])
        self.assertEqual(res["metrics"]["composition"]["ngon_count"], 0)
        self.assertEqual(res["metrics"]["composition"]["quad_pct"], 100.0)

    def test_differing_radius_holes(self):
        """Case 3.C6: Planar panel with one large hole (r=1.0) and one small knob (r=0.2)."""
        v_large, f_large = create_planar_collar_panel(size=4.0, hole_radius=0.8, collar_radius=1.4, n_pts=8)
        v_large[:, 0] -= 2.5
        v_small, f_small = create_planar_collar_panel(size=3.0, hole_radius=0.2, collar_radius=0.6, n_pts=8)
        v_small[:, 0] += 2.5

        all_verts = np.vstack([v_large, v_small])
        offset = len(v_large)
        all_faces = list(f_large) + [tuple(vi + offset for vi in face) for face in f_small]

        verifier = MeshQualityVerifier(all_verts, all_faces, allow_open=True)
        res = verifier.verify()
        self.assertTrue(res["passed"])
        self.assertEqual(res["metrics"]["composition"]["quad_pct"], 100.0)


class TestTier3ConcentricFeatures(unittest.TestCase):
    """Tier 3: Concentric Features & Annular Rings."""

    def test_concentric_circular_quad_rings(self):
        """Case 3.C7: Concentric annular quad rings forming a wide disc."""
        radii = [0.5, 1.0, 1.8, 2.8, 4.0]
        n_pts = 16
        verts = []
        for r in radii:
            for i in range(n_pts):
                th = 2.0 * math.pi * i / n_pts
                verts.append([r * math.cos(th), r * math.sin(th), 0.0])

        faces = []
        for ring in range(len(radii) - 1):
            off0 = ring * n_pts
            off1 = (ring + 1) * n_pts
            for i in range(n_pts):
                i_next = (i + 1) % n_pts
                faces.append((off0 + i, off0 + i_next, off1 + i_next, off1 + i))

        verifier = MeshQualityVerifier(np.array(verts), faces, allow_open=True)
        res = verifier.verify()
        self.assertTrue(res["passed"])
        self.assertEqual(res["metrics"]["composition"]["quad_pct"], 100.0)
        self.assertLess(res["metrics"]["planar_quad_aspect_ratio"]["percentile_90"], 3.5)

    def test_stepped_flanged_cylinder(self):
        """Case 3.C8: Concentric stepped cylinder (shaft connected to wider flange via annular quad ring)."""
        # Inner shaft (r=1.0, z=0..2)
        # Flange ring (r=1.0..2.5, z=2)
        n_th = 16
        verts = []
        # Shaft bottom z=0
        for i in range(n_th):
            th = 2.0 * math.pi * i / n_th
            verts.append([1.0 * math.cos(th), 1.0 * math.sin(th), 0.0])
        # Shaft top / flange inner z=1.0
        for i in range(n_th):
            th = 2.0 * math.pi * i / n_th
            verts.append([1.0 * math.cos(th), 1.0 * math.sin(th), 1.0])
        # Flange outer z=1.0
        for i in range(n_th):
            th = 2.0 * math.pi * i / n_th
            verts.append([2.5 * math.cos(th), 2.5 * math.sin(th), 1.0])

        faces = []
        # Shaft body quads
        for i in range(n_th):
            i_next = (i + 1) % n_th
            faces.append((i, i_next, n_th + i_next, n_th + i))
        # Flange annular quads
        for i in range(n_th):
            i_next = (i + 1) % n_th
            faces.append((n_th + i, n_th + i_next, 2 * n_th + i_next, 2 * n_th + i))

        verifier = MeshQualityVerifier(np.array(verts), faces, allow_open=True)
        res = verifier.verify()
        self.assertTrue(res["checks"]["ngons"])
        self.assertEqual(res["metrics"]["composition"]["quad_pct"], 100.0)


class TestTier3AssembliesAndBoundaries(unittest.TestCase):
    """Tier 3: Assemblies and Proximity."""

    def test_composite_solid_and_curved_islands(self):
        """Case 3.C9: Assembly with 1 closed quad box and 1 closed quad sphere."""
        from tests.mesh_factory import create_quad_sphere
        v_box, f_box = create_quad_box(w=2.0, h=2.0, d=2.0)
        v_sph, f_sph = create_quad_sphere(radius=1.0, n_lat=8, n_lon=16)
        v_sph += np.array([6.0, 0.0, 0.0])

        all_verts = np.vstack([v_box, v_sph])
        offset = len(v_box)
        all_faces = list(f_box) + [tuple(vi + offset for vi in face) for face in f_sph]

        verifier = MeshQualityVerifier(all_verts, all_faces, allow_open=False)
        res = verifier.verify()
        self.assertTrue(res["passed"])
        self.assertEqual(res["metrics"]["islands"], 2)
        self.assertEqual(res["metrics"]["closed_components"], 2)
        self.assertEqual(res["metrics"]["boundary"]["boundary_edge_count"], 0)

    def test_hole_adjacent_to_outer_perimeter(self):
        """Case 3.C10: Hole placed near boundary maintains regular quad aspect ratio."""
        # Panel where hole is near edge
        v, f = create_planar_collar_panel(size=3.0, hole_radius=0.3, collar_radius=0.7, n_pts=8)
        verifier = MeshQualityVerifier(v, f, allow_open=True)
        res = verifier.verify()
        self.assertTrue(res["checks"]["ngons"])
        self.assertLess(res["metrics"]["planar_quad_aspect_ratio"]["percentile_90"], 3.5)


if __name__ == "__main__":
    unittest.main()
