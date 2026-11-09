# Mesh Processing Pipeline Test Infrastructure

## Overview
This document describes the pure-Python, requirement-driven, opaque-box E2E test suite and automated mesh quality verification infrastructure for the generalized mesh processing pipeline.

The test infrastructure enforces the mathematical and geometric quality standards specified in `ORIGINAL_REQUEST.md` and `PROJECT.md`:
1. **Strict 0% N-gons**: All faces must be strictly quads ($k=4$) or triangles ($k=3$). No polygons with $k > 4$.
2. **Watertight & Zero Boundary Cracks**: Boundary edge count == 0 on closed components, non-manifold edge count == 0.
3. **High Quad Dominance**: Quad percentage $\ge 75.0\%$ across the output mesh.
4. **Planar Quad Aspect Ratio**: 90th percentile aspect ratio $< 3.5:1$ on planar quads; complete elimination of 1D barcode slats.
5. **Absence of Needle Slivers**: Zero needle triangles with aspect ratio $> 15.0:1$ or minimum angle $< 4.0^\circ$.

---

## Architecture of the Test Suite

The test suite is organized into 4 distinct validation tiers, ensuring progressive testability, isolation, and end-to-end coverage:

```
tests/
├── verify_mesh_quality.py   # Pure-Python CLI quality verification engine (acceptance criteria oracle)
├── mesh_factory.py          # Procedural geometric topology and fixture generation library
├── test_runner.py           # Unified multi-tier test execution runner with structured JSON export
├── test_tier1_features.py   # Tier 1: Feature Coverage (>= 5 cases per feature across 5 features = 25 tests)
├── test_tier2_boundaries.py # Tier 2: Boundary & Corner Cases (empty meshes, chevrons, high valence, slats = 17 tests)
├── test_tier3_combinations.py # Tier 3: Cross-Feature Combinations (holes on curved shells, multi-knob panels = 10 tests)
└── test_tier4_workloads.py  # Tier 4: Real-World Benchmark Workloads (woodenrack, 002, sofa, parumala = 7 tests)
```

Total Test Cases: **59 self-contained, independent unit and integration tests**.

---

## Geometric & Mathematical Verification Engine (`tests/verify_mesh_quality.py`)

`verify_mesh_quality.py` is the authoritative programmatic oracle. It parses `.obj`, `.glb`, and `.gltf` files without relying on Blender (`bpy`) or external binaries.

### Mathematical Definitions

1. **Face Arity & N-Gon Count**:
   For each face $f = (v_0, v_1, \dots, v_{k-1})$:
   - Quad: $k = 4$
   - Triangle: $k = 3$
   - N-gon: $k > 4$
   - Degenerate: $k < 3$ or duplicate vertex indices in face loop
   $$\text{Quad Dominance} = \frac{N_{\text{quads}}}{N_{\text{faces}}} \times 100\% \ge 75.0\%$$
   $$\text{N-Gon Percentage} = \frac{N_{\text{ngons}}}{N_{\text{faces}}} \times 100\% == 0.0\%$$

2. **Boundary Cracks & Manifoldness**:
   Construct edge adjacency map $E \to \{f_i\}$.
   - Boundary edge: $|link\_faces(e)| == 1$
   - Manifold edge: $|link\_faces(e)| == 2$
   - Non-manifold edge: $|link\_faces(e)| > 2$
   On closed solids, boundary edge count must be strictly $0$. Non-manifold edge count must always be $0$.

3. **Planar Quad Aspect Ratio**:
   A quad $(v_0, v_1, v_2, v_3)$ is planar if the angle between the diagonal sub-triangles $(v_0, v_1, v_2)$ and $(v_0, v_2, v_3)$ satisfies:
   $$\cos \theta = \frac{n_1 \cdot n_2}{\|n_1\| \|n_2\|} \ge \cos(5.0^\circ) \approx 0.9962$$
   Edge lengths $e_0 = \|v_1 - v_0\|$, $e_1 = \|v_2 - v_1\|$, $e_2 = \|v_3 - v_2\|$, $e_3 = \|v_0 - v_3\|$.
   $$u = \frac{e_0 + e_2}{2}, \quad v = \frac{e_1 + e_3}{2}$$
   $$\text{Aspect Ratio } AR_{\text{quad}} = \frac{\max(u, v)}{\min(u, v)}$$
   Acceptance standard: $AR_{90\text{th}} < 3.5:1$, and zero extreme 1D barcode slats ($AR > 10.0$).

4. **Needle Triangles & Slivers**:
   For each triangle $(v_0, v_1, v_2)$ with edge lengths $a, b, c$ and area $A$:
   $$h_{\min} = \frac{2 A}{\max(a, b, c)}, \quad AR_{\text{tri}} = \frac{\max(a, b, c)}{h_{\min}}$$
   Minimum internal angle $\theta_{\min}$ is computed via the law of cosines.
   A triangle is flagged as a needle sliver if:
   $$AR_{\text{tri}} > 15.0 \quad \text{or} \quad \theta_{\min} < 4.0^\circ$$
   Acceptance standard: Needle triangle count == 0.

---

## 4-Tier Test Breakdown

### Tier 1: Feature Coverage (`tests/test_tier1_features.py`)
- **Quad Grids (5 tests)**: Uniform isotropic grids, rectangular bounded AR grids, 3D rotated grids, hexahedral box topology, and regular valence-4 interior lattice.
- **Planar Faces (5 tests)**: Flat panel coplanarity, convex decomposition, tilted planes, concentric annular discs, non-annular planar partitioning.
- **Internal Hole Features (5 tests)**: Circular collar isolation, rectangular cutout isolation, small knob scale invariance, Steiner CDT fallback, and closed hole boundary loop verification.
- **Curved Surfaces (5 tests)**: Cylinder quad body, UV sphere quad-dominance, torus genus-1 manifold, hyperbolic paraboloid saddle, and variable curvature stability.
- **Boundary Loops (5 tests)**: Watertight closure, multi-component closure, unstitched boundary crack detection, non-manifold edge detection, and perimeter loop extraction.

### Tier 2: Boundary & Corner Cases (`tests/test_tier2_boundaries.py`)
- **Empty & Minimal Meshes**: 0-vertex / 0-face meshes, single quad, single triangle, minimal 2-quad strip.
- **Non-Convex Polygons**: Annular 20-gon rejection, reflex chevron quad (>180°), self-intersecting bowtie quads.
- **High-Valence Singularities**: Central vertex valence 12, valence 16 spoke starbursts, valence 24 stress.
- **Collinear & Degenerate**: Collinear zero-area triangles, duplicate face vertices, collapsed coincident edges.
- **Extreme Aspect Ratios**: 100:1 barcode slats, 100:1 needle triangles, AR 3.4 vs 3.6 threshold boundary conditions.

### Tier 3: Cross-Feature Combinations (`tests/test_tier3_combinations.py`)
- **Holes on Curved Surfaces**: Cylindrical shell with aperture, spherical cap aperture, curved saddle with hole.
- **Multiple Holes in Single Planar Panel**: Dual-knob drawer panel (target woodenrack geometry), 4-knob array, differing radius holes.
- **Concentric Features**: Concentric circular quad rings, stepped flanged cylinder.
- **Assemblies & Proximity**: Composite box + sphere assembly, hole in close proximity to outer boundary.

### Tier 4: Real-World Benchmark Workloads (`tests/test_tier4_workloads.py`)
- **Benchmark Input Verification**: Verifies presence and valid formatting of `woodenrack_854k.glb`, `002.glb`, `sofa_860k.glb`, `parumala_thirumeni.json`.
- **Reference Ground Truth**: Validates `benchmarks/parumala_thirumeni.json` ground truth metrics (0 N-gons, 71.58% quads, AR 90th% 3.39).
- **Raw Remeshed Input Quality**: Audits `woodenrack_854k__comp0000__remeshed.obj` confirming initial 99.71% quad baseline.
- **Forensic Legacy Failure Detections**: Rigorously validates that un-fixed pipeline outputs fail quality checks:
  - `outputs/woodenrack_test/woodenrack_854k__final.obj`: Flags 215 N-gons, 63.67% quads, 36 extreme barcode slats (AR max 156.93).
  - `outputs/sofa_clean_verified/sofa_860k__final.obj`: Flags 578 N-gons, 206 boundary edges.
  - `outputs/002_clean_verified/002__final.obj`: Flags 5,656 N-gons, 108 boundary edges, 8 non-manifold edges.
- **Production Output Harness**: Armed test harness ready to verify new outputs generated by `isolated_pipeline`.

---

## Execution Instructions

### Running the Unified Test Runner
```bash
# Run the complete test suite (all 4 tiers)
python3 tests/test_runner.py

# Run with verbose test-by-test logging
python3 tests/test_runner.py --verbose

# Run a specific tier only (e.g. Tier 1 or Tier 4)
python3 tests/test_runner.py --tier 1
python3 tests/test_runner.py --tier 4

# Export machine-readable JSON execution results
python3 tests/test_runner.py --json-output test_results.json
```

### Running with Standard Python `unittest`
```bash
# Discover and run all 59 tests
python3 -m unittest discover tests

# Run individual test modules
python3 tests/test_tier1_features.py
python3 tests/test_tier2_boundaries.py
python3 tests/test_tier3_combinations.py
python3 tests/test_tier4_workloads.py
```

### Running the Mesh Quality Verifier CLI
```bash
# Verify any mesh file (.obj, .glb, .gltf)
python3 tests/verify_mesh_quality.py path/to/model.obj

# Allow open boundaries (for open sheet/patch meshes)
python3 tests/verify_mesh_quality.py path/to/patch.obj --allow-open

# Machine-readable JSON output
python3 tests/verify_mesh_quality.py path/to/model.obj --json

# Strict mode (max planar AR strictly <= 3.5)
python3 tests/verify_mesh_quality.py path/to/model.obj --strict
```
Exit code is `0` if all 5 acceptance checks pass; `1` with explicit diagnostic failure messages if any check fails.
