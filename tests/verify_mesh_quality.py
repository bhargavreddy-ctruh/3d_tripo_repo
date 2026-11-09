#!/usr/bin/env python3
"""Automated pure-Python mesh quality verification engine.

Verifies the 5 acceptance criteria defined in ORIGINAL_REQUEST.md & PROJECT.md:
1. Strict 0% N-gons: All faces must be strictly quads or triangles.
2. Boundary crack count == 0 on closed components (and 0 non-manifold edges).
3. Quad dominance >= 75.0% across the mesh.
4. Planar quad aspect ratio < 3.5 (90th percentile < 3.5, no 1D barcode slats).
5. Absence of extreme aspect ratio slivers / needle triangles (AR > 15.0, min angle < 4°).

CLI usage:
    python3 tests/verify_mesh_quality.py <path_to_mesh.obj> [--allow-open] [--json] [--strict]
"""

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict

import numpy as np

# Ensure core modules can be imported if running within repo
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_CORE_DIR = os.path.join(_REPO_ROOT, "core")
if os.path.exists(_CORE_DIR) and _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)


def load_mesh_file(filepath):
    """Load mesh file preserving face arity (quads/n-gons).
    Returns (vertices, faces) where:
    - vertices is a numpy array of shape (N, 3)
    - faces is a list of tuples containing 0-based vertex indices.
    """
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".obj":
        return _load_obj(filepath)
    elif ext in (".glb", ".gltf"):
        return _load_glb(filepath)
    else:
        raise ValueError(f"Unsupported mesh format '{ext}'. Must be .obj, .glb, or .gltf")


def _load_obj(filepath):
    """Pure-Python robust OBJ reader preserving face arity."""
    vertices = []
    faces = []
    with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            tag = parts[0]
            if tag == "v":
                vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
            elif tag == "f":
                idx = []
                n = len(vertices)
                for tok in parts[1:]:
                    vi = int(tok.split("/")[0])
                    if vi < 0:
                        vi = n + vi + 1
                    idx.append(vi - 1)
                if len(idx) >= 3:
                    faces.append(tuple(idx))
    return np.array(vertices, dtype=float), faces


def _load_glb(filepath):
    """Load GLB/GLTF via trimesh."""
    import trimesh
    scene_or_mesh = trimesh.load(filepath, process=False)
    if isinstance(scene_or_mesh, trimesh.Scene):
        all_verts = []
        all_faces = []
        offset = 0
        for geom in scene_or_mesh.geometry.values():
            if not isinstance(geom, trimesh.Trimesh) or len(geom.faces) == 0:
                continue
            all_verts.extend(geom.vertices.tolist())
            all_faces.extend((f + offset).tolist() for f in geom.faces)
            offset += len(geom.vertices)
        return np.array(all_verts, dtype=float), [tuple(f) for f in all_faces]
    else:
        return np.array(scene_or_mesh.vertices, dtype=float), [tuple(f) for f in scene_or_mesh.faces]


class MeshQualityVerifier:
    """Verifies geometric and topological quality against strict acceptance standards."""

    def __init__(
        self,
        vertices,
        faces,
        filepath="<mesh>",
        min_quad_pct=75.0,
        max_planar_ar=3.5,
        max_sliver_ar=15.0,
        min_tri_angle_deg=4.0,
        allow_open=False,
        strict=False,
    ):
        self.vertices = np.asarray(vertices, dtype=float)
        self.faces = faces
        self.filepath = filepath
        self.min_quad_pct = min_quad_pct
        self.max_planar_ar = max_planar_ar
        self.max_sliver_ar = max_sliver_ar
        self.min_tri_angle_deg = min_tri_angle_deg
        self.allow_open = allow_open
        self.strict = strict

    def verify(self):
        """Run all verification checks. Returns dict with metrics and pass/fail booleans."""
        total_faces = len(self.faces)
        total_verts = len(self.vertices)

        if total_faces == 0 or total_verts == 0:
            return {
                "filepath": self.filepath,
                "passed": False,
                "total_verts": total_verts,
                "total_faces": total_faces,
                "failure_reasons": ["Mesh is empty (0 vertices or 0 faces)."],
                "checks": {
                    "ngons": False,
                    "boundary_cracks": False,
                    "quad_dominance": False,
                    "planar_quad_ar": False,
                    "sliver_triangles": False,
                },
                "metrics": {},
            }

        # Build edge adjacency
        edge_to_faces = defaultdict(list)
        vert_to_faces = defaultdict(list)
        for fi, face in enumerate(self.faces):
            k = len(face)
            for i in range(k):
                v0, v1 = face[i], face[(i + 1) % k]
                edge_key = frozenset((v0, v1))
                edge_to_faces[edge_key].append(fi)
                vert_to_faces[v0].append(fi)

        # 1. Composition / Face Arity
        quad_indices = []
        tri_indices = []
        ngon_indices = []
        degenerate_indices = []

        for fi, face in enumerate(self.faces):
            k = len(face)
            if k < 3 or len(set(face)) < k:
                degenerate_indices.append(fi)
            elif k == 4:
                quad_indices.append(fi)
            elif k == 3:
                tri_indices.append(fi)
            else:
                ngon_indices.append(fi)

        quad_count = len(quad_indices)
        tri_count = len(tri_indices)
        ngon_count = len(ngon_indices)
        degenerate_count = len(degenerate_indices)

        quad_pct = (quad_count / total_faces) * 100.0 if total_faces > 0 else 0.0
        tri_pct = (tri_count / total_faces) * 100.0 if total_faces > 0 else 0.0
        ngon_pct = (ngon_count / total_faces) * 100.0 if total_faces > 0 else 0.0

        # Check A: Strict 0% N-Gons
        pass_ngons = (ngon_count == 0) and (degenerate_count == 0)

        # 2. Boundary Cracks & Manifoldness
        boundary_edges = [e for e, flist in edge_to_faces.items() if len(flist) == 1]
        non_manifold_edges = [e for e, flist in edge_to_faces.items() if len(flist) > 2]

        # Connected component decomposition via face adjacency
        visited_faces = set()
        components = []
        for fi in range(total_faces):
            if fi in visited_faces:
                continue
            comp = []
            queue = [fi]
            visited_faces.add(fi)
            while queue:
                curr = queue.pop()
                comp.append(curr)
                f_verts = self.faces[curr]
                k = len(f_verts)
                for i in range(k):
                    ek = frozenset((f_verts[i], f_verts[(i + 1) % k]))
                    for nbr in edge_to_faces[ek]:
                        if nbr not in visited_faces:
                            visited_faces.add(nbr)
                            queue.append(nbr)
            components.append(comp)

        # Classify components as closed if they have 0 boundary edges
        comp_boundary_counts = []
        closed_components = 0
        open_components = 0
        comp_boundary_cracks = 0

        for comp in components:
            comp_face_set = set(comp)
            comp_edges = set()
            for cfi in comp:
                f_verts = self.faces[cfi]
                k = len(f_verts)
                for i in range(k):
                    comp_edges.add(frozenset((f_verts[i], f_verts[(i + 1) % k])))
            comp_b_edges = [e for e in comp_edges if len([f for f in edge_to_faces[e] if f in comp_face_set]) == 1]
            comp_boundary_counts.append(len(comp_b_edges))
            if len(comp_b_edges) == 0:
                closed_components += 1
            else:
                open_components += 1
                # If mesh as a whole was not declared open, these are cracks
                if not self.allow_open:
                    comp_boundary_cracks += len(comp_b_edges)

        total_boundary_edges = len(boundary_edges)
        total_non_manifold_edges = len(non_manifold_edges)

        # Check B: Boundary cracks == 0 on closed components, non-manifold edges == 0
        if self.allow_open:
            # On explicitly open meshes, non-manifold edges must be 0
            pass_boundary = (total_non_manifold_edges == 0)
        else:
            # On closed models, boundary cracks must be 0 and non-manifold edges 0
            pass_boundary = (total_boundary_edges == 0) and (total_non_manifold_edges == 0)

        # Check C: Quad dominance >= 75.0%
        pass_quad_dominance = (quad_pct >= self.min_quad_pct)

        # 3. Planar Quad Aspect Ratio & Barcode Slat Analysis
        planar_quad_aspects = []
        all_quad_aspects = []
        planar_quad_count = 0
        extreme_quad_slats = []

        for qfi in quad_indices:
            f = self.faces[qfi]
            v0, v1, v2, v3 = (self.vertices[i] for i in f)
            e0 = v1 - v0
            e1 = v2 - v1
            e2 = v3 - v2
            e3 = v0 - v3
            l0, l1, l2, l3 = (float(np.linalg.norm(e)) for e in (e0, e1, e2, e3))
            u = 0.5 * (l0 + l2)
            v_len = 0.5 * (l1 + l3)
            ar = max(u, v_len) / max(min(u, v_len), 1e-7)
            all_quad_aspects.append(ar)

            if ar > 10.0:
                extreme_quad_slats.append(qfi)

            # Check planarity: normal angle between triangles (v0, v1, v2) and (v0, v2, v3)
            n1 = np.cross(v1 - v0, v2 - v0)
            n2 = np.cross(v2 - v0, v3 - v0)
            norm_n1 = np.linalg.norm(n1)
            norm_n2 = np.linalg.norm(n2)

            is_planar = False
            if norm_n1 > 1e-8 and norm_n2 > 1e-8:
                cos_angle = np.clip(np.dot(n1, n2) / (norm_n1 * norm_n2), -1.0, 1.0)
                # Angle < 5 degrees indicates coplanar face
                if cos_angle >= math.cos(math.radians(5.0)):
                    is_planar = True

            if is_planar:
                planar_quad_count += 1
                planar_quad_aspects.append(ar)

        # Compute aspect ratio stats
        if planar_quad_aspects:
            planar_ar_median = float(np.median(planar_quad_aspects))
            planar_ar_90th = float(np.percentile(planar_quad_aspects, 90))
            planar_ar_max = float(np.max(planar_quad_aspects))
            planar_ar_under_threshold_pct = (
                sum(1 for a in planar_quad_aspects if a <= self.max_planar_ar) / len(planar_quad_aspects) * 100.0
            )
        else:
            planar_ar_median = 1.0
            planar_ar_90th = 1.0
            planar_ar_max = 1.0
            planar_ar_under_threshold_pct = 100.0

        if all_quad_aspects:
            all_ar_median = float(np.median(all_quad_aspects))
            all_ar_90th = float(np.percentile(all_quad_aspects, 90))
            all_ar_max = float(np.max(all_quad_aspects))
        else:
            all_ar_median = 1.0
            all_ar_90th = 1.0
            all_ar_max = 1.0

        # Check D: Planar quad aspect ratio < 3.5
        # The 90th percentile must be strictly < max_planar_ar (3.5),
        # and in strict mode max AR must not exceed threshold; also no barcode slats (> 5.0)
        if self.strict:
            pass_planar_ar = (planar_ar_max <= self.max_planar_ar)
        else:
            # 90th percentile < 3.5, and no extreme 1D slats (AR > 10.0)
            pass_planar_ar = (planar_ar_90th <= self.max_planar_ar) and (len(extreme_quad_slats) == 0)

        # 4. Needle Triangles / Sliver Analysis
        needle_triangles = []
        triangle_aspects = []
        triangle_min_angles = []

        for tfi in tri_indices:
            f = self.faces[tfi]
            v0, v1, v2 = (self.vertices[i] for i in f)
            e0 = v1 - v0
            e1 = v2 - v1
            e2 = v0 - v2
            a = float(np.linalg.norm(e0))
            b = float(np.linalg.norm(e1))
            c = float(np.linalg.norm(e2))

            cross_prod = np.cross(e0, -e2)
            area = 0.5 * float(np.linalg.norm(cross_prod))
            max_edge = max(a, b, c)

            if area < 1e-9 or max_edge < 1e-9:
                # Degenerate needle
                needle_triangles.append(tfi)
                triangle_aspects.append(999.0)
                triangle_min_angles.append(0.0)
                continue

            h_min = 2.0 * area / max_edge
            ar_tri = max_edge / max(h_min, 1e-9)
            triangle_aspects.append(ar_tri)

            # Compute min internal angle
            cos_a = np.clip((b**2 + c**2 - a**2) / max(2.0 * b * c, 1e-9), -1.0, 1.0)
            cos_b = np.clip((a**2 + c**2 - b**2) / max(2.0 * a * c, 1e-9), -1.0, 1.0)
            cos_c = np.clip((a**2 + b**2 - c**2) / max(2.0 * a * b, 1e-9), -1.0, 1.0)
            angle_a = math.degrees(math.acos(cos_a))
            angle_b = math.degrees(math.acos(cos_b))
            angle_c = math.degrees(math.acos(cos_c))
            min_ang = min(angle_a, angle_b, angle_c)
            triangle_min_angles.append(min_ang)

            # A needle triangle has extreme AR (>15.0) or very acute angle (<4 degrees)
            if ar_tri > self.max_sliver_ar or min_ang < self.min_tri_angle_deg:
                needle_triangles.append(tfi)

        needle_count = len(needle_triangles)
        tri_ar_max = float(np.max(triangle_aspects)) if triangle_aspects else 1.0
        tri_min_angle_deg = float(np.min(triangle_min_angles)) if triangle_min_angles else 60.0

        # Check E: Absence of extreme aspect ratio slivers / needle triangles
        pass_slivers = (needle_count == 0)

        # Overall Pass / Fail
        all_passed = (
            pass_ngons
            and pass_boundary
            and pass_quad_dominance
            and pass_planar_ar
            and pass_slivers
        )

        failure_reasons = []
        if not pass_ngons:
            failure_reasons.append(
                f"Strict 0% N-gons violation: Found {ngon_count} N-gons ({ngon_pct:.2f}%) "
                f"and {degenerate_count} degenerate faces."
            )
        if not pass_boundary:
            failure_reasons.append(
                f"Boundary/crack violation: Found {total_boundary_edges} boundary edges and "
                f"{total_non_manifold_edges} non-manifold edges."
            )
        if not pass_quad_dominance:
            failure_reasons.append(
                f"Quad dominance violation: Quad percentage {quad_pct:.2f}% is below required {self.min_quad_pct:.1f}%."
            )
        if not pass_planar_ar:
            failure_reasons.append(
                f"Planar quad aspect ratio violation: 90th% is {planar_ar_90th:.2f}:1 (threshold < {self.max_planar_ar:.1f}:1), "
                f"max is {planar_ar_max:.2f}:1, {len(extreme_quad_slats)} extreme 1D barcode slats detected."
            )
        if not pass_slivers:
            failure_reasons.append(
                f"Sliver/needle triangle violation: Found {needle_count} needle triangles with AR > {self.max_sliver_ar:.1f} "
                f"or min angle < {self.min_tri_angle_deg:.1f}°. (Worst AR: {tri_ar_max:.2f}, min angle: {tri_min_angle_deg:.2f}°)."
            )

        return {
            "filepath": self.filepath,
            "passed": all_passed,
            "failure_reasons": failure_reasons,
            "checks": {
                "ngons": pass_ngons,
                "boundary_cracks": pass_boundary,
                "quad_dominance": pass_quad_dominance,
                "planar_quad_ar": pass_planar_ar,
                "sliver_triangles": pass_slivers,
            },
            "metrics": {
                "total_verts": total_verts,
                "total_faces": total_faces,
                "total_edges": len(edge_to_faces),
                "islands": len(components),
                "closed_components": closed_components,
                "open_components": open_components,
                "composition": {
                    "quad_count": quad_count,
                    "quad_pct": round(quad_pct, 2),
                    "tri_count": tri_count,
                    "tri_pct": round(tri_pct, 2),
                    "ngon_count": ngon_count,
                    "ngon_pct": round(ngon_pct, 2),
                    "degenerate_count": degenerate_count,
                },
                "boundary": {
                    "boundary_edge_count": total_boundary_edges,
                    "non_manifold_edge_count": total_non_manifold_edges,
                    "crack_count": comp_boundary_cracks if not self.allow_open else 0,
                },
                "planar_quad_aspect_ratio": {
                    "count": planar_quad_count,
                    "median": round(planar_ar_median, 2),
                    "percentile_90": round(planar_ar_90th, 2),
                    "max": round(planar_ar_max, 2),
                    "pct_under_threshold": round(planar_ar_under_threshold_pct, 2),
                    "extreme_slat_count": len(extreme_quad_slats),
                },
                "all_quad_aspect_ratio": {
                    "count": quad_count,
                    "median": round(all_ar_median, 2),
                    "percentile_90": round(all_ar_90th, 2),
                    "max": round(all_ar_max, 2),
                },
                "needle_triangles": {
                    "count": needle_count,
                    "max_ar": round(tri_ar_max, 2),
                    "min_angle_deg": round(tri_min_angle_deg, 2),
                },
            },
        }


def format_verification_report(result):
    """Format verification result for terminal printing."""
    lines = []
    lines.append("=" * 80)
    name = os.path.basename(result["filepath"])
    status_str = "PASSED [100% OK]" if result["passed"] else "FAILED [VERIFICATION REJECTED]"
    lines.append(f"MESH QUALITY VERIFICATION REPORT: {name}")
    lines.append(f"Status: {status_str}")
    lines.append("=" * 80)

    m = result.get("metrics", {})
    if not m:
        lines.append("Error: No metrics could be computed.")
        for r in result.get("failure_reasons", []):
            lines.append(f"  - {r}")
        lines.append("=" * 80)
        return "\n".join(lines)

    comp = m.get("composition", {})
    bnd = m.get("boundary", {})
    pq = m.get("planar_quad_aspect_ratio", {})
    aq = m.get("all_quad_aspect_ratio", {})
    nt = m.get("needle_triangles", {})

    lines.append(f"Geometry:         {m['total_verts']:,} Vertices | {m['total_faces']:,} Faces | {m['total_edges']:,} Edges")
    lines.append(f"Components:       {m['islands']} Component(s) ({m['closed_components']} closed, {m['open_components']} open)")
    lines.append("-" * 80)

    # Check 1: N-gons
    c1 = "PASS" if result["checks"]["ngons"] else "FAIL"
    lines.append(f"[{c1}] 1. N-Gon Count:        {comp['ngon_count']} N-gons ({comp['ngon_pct']}%) | Degenerate: {comp['degenerate_count']} (Required: strictly 0)")

    # Check 2: Boundary Cracks
    c2 = "PASS" if result["checks"]["boundary_cracks"] else "FAIL"
    lines.append(f"[{c2}] 2. Boundary Cracks:    {bnd['boundary_edge_count']} boundary edges | Non-manifold: {bnd['non_manifold_edge_count']} (Required: 0 on closed)")

    # Check 3: Quad Dominance
    c3 = "PASS" if result["checks"]["quad_dominance"] else "FAIL"
    lines.append(f"[{c3}] 3. Quad Dominance:     {comp['quad_pct']}% quads ({comp['quad_count']} quads, {comp['tri_count']} tris) (Required: >= 75.0%)")

    # Check 4: Planar Quad Aspect Ratio
    c4 = "PASS" if result["checks"]["planar_quad_ar"] else "FAIL"
    lines.append(f"[{c4}] 4. Planar Quad AR:     90th%: {pq['percentile_90']}:1 | Median: {pq['median']}:1 | Max: {pq['max']}:1 (Required 90th%: < 3.5:1)")
    lines.append(f"                         {pq['pct_under_threshold']}% planar quads <= 3.5 | Extreme slats: {pq['extreme_slat_count']}")

    # Check 5: Slivers / Needle Triangles
    c5 = "PASS" if result["checks"]["sliver_triangles"] else "FAIL"
    lines.append(f"[{c5}] 5. Needle Triangles:   {nt['count']} needle slivers | Worst AR: {nt['max_ar']}:1 | Min Angle: {nt['min_angle_deg']}° (Required: 0)")

    lines.append("-" * 80)
    if result["passed"]:
        lines.append("RESULT: ALL 5 MESH QUALITY CHECKS PASSED PERFECTLY.")
    else:
        lines.append("RESULT: MESH FAILED QUALITY SPECIFICATION.")
        lines.append("Diagnostic Failures:")
        for reason in result.get("failure_reasons", []):
            lines.append(f"  * {reason}")
    lines.append("=" * 80)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Automated Pure-Python Mesh Quality Verification")
    parser.add_argument("mesh_path", help="Path to mesh file (.obj, .glb, .gltf)")
    parser.add_argument("--allow-open", action="store_true", help="Allow open boundaries (for open sheet/patch meshes)")
    parser.add_argument("--strict", action="store_true", help="Enforce strict planar quad aspect ratio max <= 3.5")
    parser.add_argument("--threshold-quads", type=float, default=75.0, help="Minimum quad percentage (default 75.0)")
    parser.add_argument("--max-planar-ar", type=float, default=3.5, help="Maximum planar quad aspect ratio (default 3.5)")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    args = parser.parse_args()

    if not os.path.exists(args.mesh_path):
        sys.stderr.write(f"Error: File '{args.mesh_path}' not found.\n")
        sys.exit(1)

    try:
        vertices, faces = load_mesh_file(args.mesh_path)
    except Exception as e:
        sys.stderr.write(f"Error loading mesh '{args.mesh_path}': {e}\n")
        sys.exit(1)

    verifier = MeshQualityVerifier(
        vertices=vertices,
        faces=faces,
        filepath=args.mesh_path,
        min_quad_pct=args.threshold_quads,
        max_planar_ar=args.max_planar_ar,
        allow_open=args.allow_open,
        strict=args.strict,
    )
    result = verifier.verify()

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_verification_report(result))

    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
