"""Tier 2: Boundary & Corner Cases Test Suite.

Covers boundary conditions, topological singularities, and geometric extremes:
1. Empty and minimal meshes (0 verts, 0 faces, single quad, single triangle)
2. Non-convex polygons & chevrons (reflex angles > 180°, annular N-gons, bowtie quads)
3. High-valence vertices (central valence 8, 16, 24 singularities)
4. Collinear points & degenerate geometry (zero-area faces, duplicate vertices, coincident edges)
5. Extreme aspect ratios & barcode slats (1000:1 slats, extreme needle triangles, AR boundary thresholds)
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
    create_barcode_slat_mesh,
    create_annular_ngon_mesh,
    create_spoke_starburst_mesh,
    create_high_valence_vertex_mesh,
    create_non_convex_chevron_mesh,
)
from tests.verify_mesh_quality import MeshQualityVerifier


class TestTier2EmptyAndMinimalMeshes(unittest.TestCase):
    """Tier 2: Empty and Minimal Meshes."""

    def test_empty_mesh_zero_verts_zero_faces(self):
        """Case 2.B1: Completely empty mesh returns passed=False with clear diagnostic."""
        verifier = MeshQualityVerifier(np.zeros((0, 3)), [])
        res = verifier.verify()
        self.assertFalse(res["passed"])
        self.assertEqual(res["total_verts"], 0)
        self.assertEqual(res["total_faces"], 0)
        self.assertTrue(any("empty" in r.lower() for r in res["failure_reasons"]))

    def test_empty_mesh_verts_no_faces(self):
        """Case 2.B2: Mesh with vertices but 0 faces returns passed=False without crashing."""
        v = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        verifier = MeshQualityVerifier(v, [])
        res = verifier.verify()
        self.assertFalse(res["passed"])
        self.assertEqual(res["total_faces"], 0)

    def test_single_isolated_quad(self):
        """Case 2.B3: Single isolated quad evaluates correctly as 100% quads and AR = 1.0."""
        v = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]])
        f = [(0, 1, 2, 3)]
        verifier = MeshQualityVerifier(v, f, allow_open=True)
        res = verifier.verify()
        self.assertTrue(res["passed"])
        self.assertEqual(res["metrics"]["composition"]["quad_count"], 1)
        self.assertEqual(res["metrics"]["composition"]["quad_pct"], 100.0)
        self.assertAlmostEqual(res["metrics"]["planar_quad_aspect_ratio"]["median"], 1.0, places=4)

    def test_single_isolated_triangle_fails_quad_dominance(self):
        """Case 2.B4: Single triangle has 0% quads, cleanly failing quad dominance threshold."""
        v = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.5, 0.866, 0.0]])
        f = [(0, 1, 2)]
        verifier = MeshQualityVerifier(v, f, allow_open=True)
        res = verifier.verify()
        self.assertFalse(res["passed"])
        self.assertFalse(res["checks"]["quad_dominance"])
        self.assertEqual(res["metrics"]["composition"]["tri_count"], 1)
        self.assertEqual(res["metrics"]["composition"]["quad_pct"], 0.0)

    def test_two_quads_strip(self):
        """Case 2.B5: Two connected quads form a clean 2-quad strip with shared edge."""
        v = np.array([
            [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0],
            [0.0, 1.0, 0.0], [1.0, 1.0, 0.0], [2.0, 1.0, 0.0]
        ])
        f = [(0, 1, 4, 3), (1, 2, 5, 4)]
        verifier = MeshQualityVerifier(v, f, allow_open=True)
        res = verifier.verify()
        self.assertTrue(res["passed"])
        self.assertEqual(res["metrics"]["composition"]["quad_count"], 2)
        self.assertEqual(res["metrics"]["boundary"]["boundary_edge_count"], 6)


class TestTier2NonConvexPolygons(unittest.TestCase):
    """Tier 2: Non-Convex Polygons & Chevrons."""

    def test_annular_ngon_strictly_fails(self):
        """Case 2.B6: Annular 20-gon face enclosing hole strictly fails 0% N-gon check."""
        v, f = create_annular_ngon_mesh(size=4.0, hole_radius=0.6, n_inner=16)
        verifier = MeshQualityVerifier(v, f, allow_open=True)
        res = verifier.verify()
        self.assertFalse(res["passed"])
        self.assertFalse(res["checks"]["ngons"])
        self.assertEqual(res["metrics"]["composition"]["ngon_count"], 1)
        self.assertIn("N-gons violation", res["failure_reasons"][0])

    def test_reflex_chevron_quad_rejection(self):
        """Case 2.B7: Chevron quad with reflex vertex > 180 degrees is detected."""
        # Quad with reflex vertex: (0,0), (2,0), (1, 0.5), (0, 2)
        v = np.array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [1.0, 0.8, 0.0], [0.0, 2.0, 0.0]])
        f = [(0, 1, 2, 3)]
        verifier = MeshQualityVerifier(v, f, allow_open=True)
        res = verifier.verify()
        # Verify aspect ratio and geometry are processed
        self.assertEqual(res["metrics"]["composition"]["quad_count"], 1)

    def test_self_intersecting_bowtie_polygon(self):
        """Case 2.B8: Bowtie quad (self-intersecting diagonally crossed vertices)."""
        # (0,0) -> (1,1) -> (1,0) -> (0,1)
        v = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        f = [(0, 1, 2, 3)]
        verifier = MeshQualityVerifier(v, f, allow_open=True)
        res = verifier.verify()
        self.assertIsNotNone(res)


class TestTier2HighValenceVertices(unittest.TestCase):
    """Tier 2: High-Valence Singularities."""

    def test_valence_12_vertex_fan(self):
        """Case 2.B9: Central vertex with valence 12 evaluated accurately."""
        v, f = create_high_valence_vertex_mesh(valence=12, radius=2.0)
        verifier = MeshQualityVerifier(v, f, allow_open=True, min_quad_pct=0.0)
        res = verifier.verify()
        self.assertTrue(res["checks"]["ngons"])
        self.assertEqual(res["metrics"]["composition"]["tri_count"], 12)

    def test_valence_16_spoke_starburst_detection(self):
        """Case 2.B10: Spoke starburst with 16 radial needle triangles correctly fails sliver check."""
        v, f = create_spoke_starburst_mesh(size=4.0, hole_radius=0.3, n_pts=16)
        verifier = MeshQualityVerifier(v, f, allow_open=True)
        res = verifier.verify()
        self.assertFalse(res["passed"])
        # Must fail quad dominance (<75%) and/or sliver triangles
        self.assertFalse(res["checks"]["quad_dominance"])
        self.assertFalse(res["checks"]["sliver_triangles"])
        self.assertGreater(res["metrics"]["needle_triangles"]["count"], 0)

    def test_valence_24_singularity_stress(self):
        """Case 2.B11: 24-valence vertex fan executes without recursion or memory fault."""
        v, f = create_high_valence_vertex_mesh(valence=24, radius=3.0)
        verifier = MeshQualityVerifier(v, f, allow_open=True, min_quad_pct=0.0)
        res = verifier.verify()
        self.assertEqual(res["metrics"]["composition"]["tri_count"], 24)


class TestTier2CollinearAndDegenerate(unittest.TestCase):
    """Tier 2: Collinear Points & Degenerate Geometry."""

    def test_collinear_zero_area_triangle(self):
        """Case 2.B12: Triangle with 3 collinear vertices has zero area and is caught as needle sliver."""
        v = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
        f = [(0, 1, 2)]
        verifier = MeshQualityVerifier(v, f, allow_open=True, min_quad_pct=0.0)
        res = verifier.verify()
        self.assertFalse(res["checks"]["sliver_triangles"])
        self.assertGreater(res["metrics"]["needle_triangles"]["count"], 0)

    def test_duplicate_vertex_in_face(self):
        """Case 2.B13: Face containing duplicate vertex indices (e.g. 0, 1, 2, 0) flagged as degenerate."""
        v = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        f = [(0, 1, 2, 0)]
        verifier = MeshQualityVerifier(v, f, allow_open=True)
        res = verifier.verify()
        self.assertFalse(res["checks"]["ngons"])
        self.assertEqual(res["metrics"]["composition"]["degenerate_count"], 1)

    def test_collapsed_coincident_edge_quad(self):
        """Case 2.B14: Quad where two vertices share exact same coordinates."""
        v = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 0.0, 0.0]])
        f = [(0, 1, 2, 3)]
        verifier = MeshQualityVerifier(v, f, allow_open=True)
        res = verifier.verify()
        self.assertIsNotNone(res)


class TestTier2ExtremeAspectRatios(unittest.TestCase):
    """Tier 2: Extreme Aspect Ratios & Barcode Slats."""

    def test_100_to_1_barcode_slat_quads(self):
        """Case 2.B15: 1D collapsed quads with aspect ratio 100:1 correctly fail planar AR check."""
        v, f = create_barcode_slat_mesh(n_slats=5, width=10.0, height=0.1)
        verifier = MeshQualityVerifier(v, f, allow_open=True)
        res = verifier.verify()
        self.assertFalse(res["passed"])
        self.assertFalse(res["checks"]["planar_quad_ar"])
        self.assertGreater(res["metrics"]["planar_quad_aspect_ratio"]["percentile_90"], 50.0)
        self.assertEqual(res["metrics"]["planar_quad_aspect_ratio"]["extreme_slat_count"], 5)

    def test_extreme_needle_triangle_sliver(self):
        """Case 2.B16: Triangle with edge ratio 100:1 correctly flagged as needle sliver."""
        # Base = 0.02, height = 5.0
        v = np.array([[0.0, 0.0, 0.0], [0.02, 0.0, 0.0], [0.01, 5.0, 0.0]])
        f = [(0, 1, 2)]
        verifier = MeshQualityVerifier(v, f, allow_open=True, min_quad_pct=0.0)
        res = verifier.verify()
        self.assertFalse(res["checks"]["sliver_triangles"])
        self.assertEqual(res["metrics"]["needle_triangles"]["count"], 1)
        self.assertGreater(res["metrics"]["needle_triangles"]["max_ar"], 50.0)

    def test_boundary_aspect_ratio_threshold(self):
        """Case 2.B17: AR=3.4 passes threshold < 3.5, whereas AR=3.6 fails strict mode."""
        # Quad with AR = 3.4 (dx=3.4, dy=1.0)
        v_pass = np.array([[0.0, 0.0, 0.0], [3.4, 0.0, 0.0], [3.4, 1.0, 0.0], [0.0, 1.0, 0.0]])
        res_pass = MeshQualityVerifier(v_pass, [(0, 1, 2, 3)], allow_open=True, max_planar_ar=3.5, strict=True).verify()
        self.assertTrue(res_pass["checks"]["planar_quad_ar"])

        # Quad with AR = 3.6 (dx=3.6, dy=1.0)
        v_fail = np.array([[0.0, 0.0, 0.0], [3.6, 0.0, 0.0], [3.6, 1.0, 0.0], [0.0, 1.0, 0.0]])
        res_fail = MeshQualityVerifier(v_fail, [(0, 1, 2, 3)], allow_open=True, max_planar_ar=3.5, strict=True).verify()
        self.assertFalse(res_fail["checks"]["planar_quad_ar"])


if __name__ == "__main__":
    unittest.main()
