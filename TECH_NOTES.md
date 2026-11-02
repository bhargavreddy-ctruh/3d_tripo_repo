# vacuum_quad_engine — Tech Notes

Single source of truth for what this pipeline uses and why. Update this
file the moment anything changes — a library swap, a threshold rethought,
a module renamed/split. Never let it go stale.

## Primary objective (recap — see plan file for full text)

No fixed face-count target/budget anywhere. Zero feature loss is the hard
constraint; minimum face count under that constraint is the goal. Output
must read as genuine Tripo-level anisotropic, structured, quad-dominant
flow — stretched quads on flat regions, triangles only as topological
valves, no unnecessary edges. Must generalize to arbitrary AI-generated
meshes, not just the validation corpus.

## Binaries / external tools

| Tool | Path (this machine) | Used for | Notes |
|---|---|---|---|
| Blender | `/Applications/Blender.app/Contents/MacOS/Blender` (5.2.3 LTS) | All mesh I/O, bmesh operations, curvature-adjacent geometry ops, rendering previews | Invoked via `--background --python-expr`/`--python <script>` subprocesses, same pattern as tripo_smart_engine |
| Instant Meshes | `/Users/bhargavreddy/Downloads/bhargav's one/tools/Instant Meshes.app/Contents/MacOS/Instant Meshes` | Primary field-aligned quad remesher (`-D -S 1 -d -b -r 4 -p 4 -c <deg> -f <hint>`) | GUI mode has repeated crash logs in `~/Library/Logs/DiagnosticReports` (2026-10-31) — CLI batch mode (`-o`, no GUI) tested clean 2026-11-01. Always invoke headless/batch; never open its GUI. |
| quadriflow | `vacuum_quad_engine/bin/quadriflow` | Fallback field-aligned remesher if Instant Meshes misbehaves on a given asset | Already proven stable in `tripo-logic-approach-v2` |

`core/config.py` resolves both and picks `DEFAULT_REMESH_BACKEND` automatically
(prefers Instant Meshes when present). `remesh.py` must support both and
allow a per-component fallback to quadriflow if Instant Meshes fails/crashes
on that component.

## Python libraries

| Library | Version (this machine) | Used for |
|---|---|---|
| trimesh | 5.0.0 | Mesh loading/validation outside Blender, watertight/winding checks, proximity/deviation sampling |
| numpy | 2.5.1 | Array math throughout |
| libigl (`igl`) | available | Per-vertex curvature (principal/Gaussian curvature) in `curvature.py` |
| bpy | via Blender 5.2.3 | All mesh-editing operations (decompose, remesh I/O, dissolve, darts, caps, reproject) |

## Module map (`core/`)

| Module | Purpose | Lineage |
|---|---|---|
| `config.py` | binary paths, tunables | new (done — T0) |
| `io_blender.py` | FBX/GLB/OBJ import/export via bpy, per-object stats | new, reuses tripo_smart_engine's `decomposer.py` import/export flag patterns (`forward_axis='NEGATIVE_Z', up_axis='Y'`) |
| `curvature.py` | per-vertex curvature field on the dense input mesh | new — none of the 3 prior efforts have this |
| `decompose.py` | split mesh into connected components (NOT joined into one) | new — direct fix of tripo_smart_engine's `decomposer.py` joining everything into 1 object |
| `sizing.py` | per-component curvature-integrated target_faces HINT (not a budget) | new, formula user-confirmed: `h(v) = clip(sqrt(epsilon/max(kappa,floor)), h_min, h_max)` |
| `remesh.py` | Instant Meshes (or quadriflow) invocation, once per component | adapted from tripo_smart_engine's `remesher.py`, made per-component |
| `protect.py` | continuous curvature-weighted edge protection/cost, LOCAL per-component micro-feature baseline | adapted from `ribbon_engine.py`'s Step 1 protection mask; fixes its global-median bug |
| `dissolve.py` | transverse-loop + straight-slat dissolution driven by continuous cost | ports `trace_full_transverse_loop`/`trace_straight_loop` from `ribbon_engine.py` near-verbatim, replaces its fixed 3°/18° tier gating |
| `darts.py` | coplanar triangle-pair / diamond-dart merging | ports `apply_diamond_dart_adapters` from `ribbon_engine.py` |
| `caps.py` | parallel-chord quad caps for near-planar circular boundaries | ports the bevel-ring + chord-strip construction from `burger_stand_retopo.py` |
| `reproject.py` | CAD-surface shrinkwrap onto original dense mesh | ports Step 3.5 from `ribbon_engine.py` |
| `audit.py` | forensic metrics (quad%, valence-4%, boundary edges, aspect ratios) | ported as-is from tripo_smart_engine's `audit.py` (already verified accurate) |
| `pipeline.py` | orchestrates all of the above | new, modeled on tripo_smart_engine's `pipeline.py` staging |

## Thresholds and their scale-dependence

| Threshold | Value | Scale-independent? |
|---|---|---|
| `CREASE_DEG` | 18.0° | yes (angle) |
| `TIER1_FLAT_DEG` | 3.0° | yes (angle) — used as a *continuous cost input*, not a hard tier boundary, per the Primary objective |
| `MICRO_FEATURE_CURVE_DEG` | 12.0° | yes (angle) |
| `MICRO_FEATURE_AREA_FRAC` | 0.15 (fraction of LOCAL per-component median face area) | yes (relative fraction, and now local instead of global — fixes the jade-sword-hilt bug) |
| `DOME_SADDLE_DEG` | 28.0° | yes (angle) |
| `COPLANAR_DART_DEG` | 24.0° | yes (angle) |
| `PLANAR_STRAIGHTEN_DEG` | 3.0° | yes (angle) |
| weld distance | *(to be set in `io_blender.py`)* | must be `k * bbox_diagonal`, never an absolute unit — per Generalization requirement |
| BVH outward-normal ray-hit distance (ribbon_engine had a hardcoded 0.35 units) | *(to be re-derived)* | must be `k * bbox_diagonal` when ported, NOT kept as a fixed 0.35 |

## Test corpus

- `vacuum_quad_engine/assets/inputs/`: `000-004.glb`, `Beetle_Car.glb`,
  `furn16_woodenrack_raw_854k.glb`, `jade_sword.glb`, koala glb,
  `testsample1_raw_860k.glb` (sofa), `c1.obj`, `tripo_futuristic_robot.fbx`,
  `tripo_robot_reference.fbx`.
- `/Users/bhargavreddy/tripo-smart meshes/*.fbx`: 8 genuine Tripo exports
  (wooden dresser, futuristic robot, smiley face, t-rex, cute dragon,
  fantasy character, stylized female, parumala_thirumeni) — used for
  feature/flow comparison against known-good reference wireframes.
- Held out from threshold-tuning (generalization check, per plan):
  `000.glb`-`004.glb`, `Beetle_Car.glb`, koala glb, `c1.obj` (not
  Tripo-sourced, not used to derive any threshold above).

## Known reference stats (measured this session, for comparison only — not targets)

| File | Quad% | Valence-4% | Islands |
|---|---|---|---|
| wooden dresser | 81.6% | 85.6% | 36 |
| futuristic robot | 65.2% | 69.4% | 88 |
| smiley face | 89.2% | 91.2% | 12 |
| t-rex | 85.2% | 89.2% | 51 |
| cute dragon | 89.3% | 86.8% | 4 |
| fantasy character | 59.5% | 63.8% | 29 |
| stylized female | 92.9% | 91.9% | 6 |
| parumala_thirumeni | 71.6% | 74.6% | 3 |

## Verification discipline (user instruction, 2026-11-01)

"Make sure to output of every step thoroughly before moving to next step,
cause later we should not be wondering where the problem is coming from."
Applies for the rest of implementation: every task gets an actual visual
or data-level check before being marked done in PROGRESS.md, not just an
aggregate number. T6 is the example — 68% hard-protected looked alarming
as a bare number, but a rendered wireframe immediately showed it was
correct (tube rings vs. rail lengths). Keep doing this: render, don't just
count.

## Real bugs found via generality testing (2026-11-01)

Testing `remesh.py` across the dresser AND jade_sword corpora (not just the
one asset originally used to build it) surfaced two genuine, previously
invisible failure modes — exactly why every step gets rendered/measured
before moving on:

1. **Instant Meshes can silently fragment a solid single-island component
   into hundreds of disconnected shrapnel pieces**, with exit code 0 and a
   valid-looking OBJ written — not caught by "did the subprocess succeed."
   Confirmed concretely on dresser `comp0003` (a divided open-top box): 1
   island in, 407 islands out at the real target_faces hint, STILL 20+
   islands out even forced down to `target_faces=50`, so it's a genuine
   geometry-handling failure, not a density/upsampling artifact. Fixed in
   `remesh.py`: `count_islands()`/`is_fragmented()` (via trimesh
   `mesh.split`) now gates every backend's output; a fragmented result is
   rejected and the other backend is tried; if BOTH backends fragment, the
   component is passed through UNCHANGED (`backend: "passthrough_unremeshed"`)
   rather than shipping shrapnel — a strictly safe degradation under the
   Primary objective (zero feature loss outranks face reduction).
1b. **quadriflow also has its own distinct failure mode**: an internal
   solver error (`wrong init 56 58!` printed to stdout) that aborts WITHOUT
   writing the output file, but still exits with return code 0 — not a
   crash signal, not a nonzero exit, just silently no output. Confirmed
   unrelated to the space characters in Tripo's own filenames (reproduced
   identically against a copy at a space-free path). `remesh_quadriflow`'s
   existing `ok = rc==0 and os.path.exists(out_obj) and getsize>0` check
   already catches this correctly (file-existence check, not exit-code
   trust) — flagging only so a future reader doesn't "fix" the exit-code
   check and reintroduce a silent failure.

Net effect on the full corpus so far: dresser 11/36 (31%) and jade_sword
9/107 (8%) of components end up on `passthrough_unremeshed` — both real
field-aligned remeshers (Instant Meshes AND quadriflow) failing on the
same small/oddly-shaped piece often enough to matter, not a rare edge
case. This is an acceptable, SAFE outcome per the Primary objective (zero
feature loss beats face reduction), but a meaningfully high rate — worth
revisiting in a later pass (e.g. retry with a different seed/flag set
before giving up, or a simple quadric-decimation quad-pairing as a third
automatic backend) rather than accepting it as a ceiling. `pipeline.py`
(T11) and `darts.py`/`caps.py` (T8) must treat passthrough (still-
triangulated) components as a normal, expected input, not an error case.

2. **Instant Meshes is unreliable on small/low-target-face components.**
   On jade_sword's 107 (small, ornamental) components, Instant Meshes only
   produced a clean result on 5/107 — the rest fell back to quadriflow (93)
   or passthrough (9, where even quadriflow fragmented). On the dresser's
   larger components it was mostly fine. Working hypothesis: Instant
   Meshes' field solver becomes unstable at very low absolute target face
   counts (teens-to-low-hundreds) regardless of geometry. Not yet changed
   `DEFAULT_REMESH_BACKEND` selection logic to account for this — the
   automatic per-component fallback already in `remesh_component` handles
   it correctly either way, just worth knowing the fallback is doing real,
   frequent work on small-part-heavy assets, not just a rare safety net.

## T7 dissolve: area has no single correct value for non-planar geometry

Key lesson, worth remembering for any future mesh-simplification work in
this project: once a merged face is non-planar (the normal case for any
curved real component, not an edge case), "surface area" stops being a
well-defined invariant — different valid computation methods (bmesh's
Newell-projection `calc_area()`, a from-scratch vertex-fan triangulated
sum, trimesh's own triangulation) can legitimately disagree by 30%+ on the
exact same geometry, independent of whether anything was actually lost.
The only trustworthy, planarity-independent invariant for a dissolve
operation (which never moves a vertex) is that boundary-edge count can
never increase. Area is now tracked as an informational stat in
`dissolve.py`'s output, not a pass/fail gate — verified instead by the
boundary-edge check plus a direct render/watertight spot-check.

## Important: test inputs must be DENSE/raw, not Tripo's own clean output

The 8 FBX files in `/Users/bhargavreddy/tripo-smart meshes/` are Tripo's
OWN finished, already-optimized low-poly exports — they are the TARGET to
match, not representative INPUT for this pipeline. Feeding one back through
decompose→size→remesh→dissolve re-processes an already-minimal mesh, which
is a real but out-of-scope stress test: the first full pipeline run on
`wooden dresser 3d model.fbx` produced LOWER quad%/valence-4% (67.94%/
50.2%) than the input already had (81.6%/85.6%) — not because the engine
regressed, but because there is very little genuine curvature-driven
density variation left to exploit in an already-clean reference mesh, and
re-remeshing it at a hint derived from its own (already low) face count is
a different problem than the intended dense-AI-scan-to-clean pipeline. Any
future quality comparison must run on a genuinely dense/raw input
(`furn16_woodenrack_raw_854k.glb`, the dense per-component OBJs under
`assets/inputs/`, or the dense pre-Tripo source of any reference asset) and
compare the RESULT against the Tripo reference — never feed the reference
itself back through the pipeline as if it were raw input.

## Real bug: sizing.py's target_faces_hint formula (found via raw single-blob asset test)

`target_faces_hint = area / mean(h)^2` (a SIMPLE, unweighted mean of the
per-vertex target edge length h) catastrophically under-sized a genuinely
raw, single-connected-component dense asset: the 854k-tri wooden rack GLB
(no pre-segmented parts, unlike Tripo's own already-segmented exports)
collapsed to 133 faces with every leg missing. Root cause: an unweighted
mean of h is dominated by whichever region has the most VERTICES, which on
a roughly-uniform dense scan is the large flat panels — a thin, high-
curvature leg barely moves the mean even though it's exactly the region
needing a small h. Fixed in `sizing.py` to the correct AREA-WEIGHTED
INTEGRAL: `sum_i(local_vertex_area_i / h_i^2)`, giving each region face
budget proportional to its OWN area and curvature, not diluted by vertex
count elsewhere. Confirmed fix: rack target_faces_hint 984 → 43,423;
final output 133 → 3,431 faces with all 4 legs and the divider/shelf
structure restored (visually confirmed, see `rack_fixed_HONEST.png`).

## Methodology fix: honest (non-triangulated) rendering

`trimesh.load(..., force='mesh')` always triangulates every face
internally, including clean quads and clean flat n-gons — so a genuinely
clean quad-dominant mesh and a real triangle fan render IDENTICALLY via
`Poly3DCollection(v[f])` (both show a diagonal through every face). This
caused a real misdiagnosis earlier this session (the 002.glb "chaotic
triangle fan" claim, later walked back). All visual QA from here on uses a
custom OBJ loader that preserves real face sizes and feeds variable-length
polygons directly to `Poly3DCollection` — no forced triangulation. Any
future render/screenshot MUST use this method, not `trimesh.load(...,
force='mesh')`, or it will misrepresent true quad/n-gon cleanliness.

## 8-asset Tripo reference benchmark (averaged, not single-asset)

Per user request, built `benchmarks/tripo_reference_average.json` from
`core/audit.py` run on all 8 real Tripo FBX references (not just one).
MEDIAN is the primary comparison metric (the wooden dresser reference has
one extreme 1768:1 outlier sliver quad that badly skews the mean for
aspect ratios). Median benchmark: quads_pct 83.38%, valence_4_pct 86.21%,
triangles_paired_pct 83.07%, aspect_median 1.735, aspect_90th 3.63,
aspect_max 28.42, parallelism_median 0.993, boundary_edges 129,
non_manifold_edges 8.5, islands 20.5. Per-asset raw numbers are the
sibling JSON files in `benchmarks/`.

## Module map addition: `core/coplanar_merge.py`

| Module | Purpose | Lineage |
|---|---|---|
| `coplanar_merge.py` | general flood-fill merge of any adjacent, near-coplanar faces regardless of valence/shape — fixes the "stale edge" gap `dissolve.py`+`darts.py` leave behind | new; algorithm/lessons reused from the OLD tripo-logic-approach-v2 `retopo/coplanar_merge.py` (different codebase, not copied code) |

Runs in `finalize_component.py` between `darts` and `caps`. Unlike that
older Python-only implementation (which had to re-triangulate each
cluster's boundary independently via 2D projection, and therefore could
produce two different, duplicate triangles at a shared 3-region corner),
this version hands each cluster directly to `bmesh.ops.dissolve_faces`,
which operates on the real shared mesh topology — a vertex shared by two
clusters is one shared `BMVert` throughout, so the old duplicate-triangle
failure mode doesn't apply here at all. The real failure modes this
version has instead (and fixes): `protect.py`'s dome/saddle rule being
unreliable on already-processed meshes (see below), and
`dissolve_faces(use_verts=True)` corrupting vertices shared outside the
cluster.

## Real bugs found building coplanar_merge.py (2026-11-01)

1. **`protect.py`'s dome/saddle rule is unreliable once the mesh has
   already been through dissolve/darts.** Measured directly: 72% of the
   rack's edges were dome/saddle-flagged on an asset that's mostly flat
   panels. The rule computes a vertex's mean face-normal deviation from
   the average of its surrounding faces — fine on a fresh remesh, but
   `dissolve_edges`/`dissolve_faces` can leave slightly non-planar merged
   n-gons (established earlier, see the dissolve.py area-drift section),
   and THEIR Newell-computed normals are noisier than a clean quad's,
   which the dome/saddle check misreads as a pole. Lesson: don't reuse
   `protect.py`'s hard-protected set at a pipeline stage running after
   geometry has already been merged/warped by earlier stages — recompute
   a minimal, purpose-built check instead (coplanar_merge.py's own direct
   per-edge angle test, at a much tighter 2° tolerance than protect.py's
   18° crease threshold, which makes it a sufficient safety check on its
   own).
2. **`bmesh.ops.dissolve_faces(..., use_verts=True)` can corrupt topology
   outside the dissolved region.** `use_verts=True` deletes a vertex that
   becomes "redundant" (e.g. collinear) after the merge — but if that
   vertex is ALSO used by a face outside the cluster being dissolved (a
   T-junction), deleting it corrupts that other face. Confirmed directly:
   a trivial 2-face cluster that passed a disk-topology pre-check still
   grew the mesh's boundary-edge count by 3. Fixed with `use_verts=False`
   (never deletes a vertex, so the op can only ever remove edges strictly
   internal to the given face set — provably boundary-safe) plus an
   `_is_disk_topology` pre-check (reject any cluster whose boundary isn't
   a single simple loop) as defense in depth, found via a dedicated
   per-cluster debug script, not guessed.

Net result, measured on real pipeline output: rack stray-edge fraction
(near-coplanar, non-triangle-pair interior edges) 30.9% → 4.4%, sofa
9.0% → 0.9%, zero boundary-edge growth on either asset.

## valence-4% metric: mostly a coplanar_merge artifact, not a real regularity gap

The earlier "40-52% vs Tripo's 86% median" valence-4% comparison was
measuring something different than it appeared to. Restricting the
measurement to vertices touching ONLY quad faces (no n-gon, no triangle)
isolates genuine quad-flow regularity: 002.glb 78.3% (close to Tripo's
median), rack/sofa 65.3%/54.7% on tiny samples (147/86 verts — most
vertices now touch a `coplanar_merge`-created n-gon, which is the correct,
desirable outcome, not a flaw). Any future quality comparison against the
Tripo benchmark should measure valence-4% this way (quad-only-touching
vertices), not the raw aggregate, once large flat regions exist in the
output — same caveat already noted for `quads_pct`.

## Lattice straightening: tested, reverted, kept for reference

`experimental/lattice_straighten.py` nudges a valence-4 vertex toward its
opposite-neighbor midpoint when its 4 surrounding faces are near-coplanar
(ported from the original ribbon_engine reference design). Tested in
isolation first: a real win on a smoothly-curved component (dresser tube,
460→429/418 faces). Wired into `finalize_component.py`, then reverted
after a FULL real-asset pipeline run (the wooden rack, mostly flat panels)
showed a net regression (1125→1189 faces) despite an unchanged stray-edge
fraction. Likely mechanism: a locally-correct straightening nudge can
perturb a vertex's face normal just enough to drop it out of a LARGER
coplanar region's tolerance, fragmenting what `coplanar_merge` would
otherwise merge as one big cluster. Lesson for this project generally: an
isolated single-component test, even a real and honest one, is not
sufficient evidence to merge a change — a full end-to-end run on a
different asset SHAPE can contradict it. The module is kept (not deleted)
with this note, since it may still be useful gated on a per-component
curvature heuristic (e.g. only apply where the component is NOT mostly
flat) rather than applied universally.

## Boundary collinear-vertex cleanup (new pipeline stage)

`coplanar_merge.dissolve_collinear_vertices` is now called in
`finalize_component.py` right after `coplanar_merge.merge_coplanar_regions`.
Fixes a real, user-observed, visually distinct defect from the earlier
"stray edges" fix: a correctly merged flat n-gon's own BOUNDARY can still
look like many small jagged segments instead of one clean line, because
`merge_coplanar_regions` deliberately never removes a vertex
(`use_verts=False`, for T-junction safety). This cleanup only targets
valence-2 vertices (never shared with other geometry by construction, so
no T-junction risk) that sit exactly on the line between their two
neighbors — exact, not an approximation. Measured on the real pipeline:
rack verts 4,553→2,231 (-51%), sofa 1,906→1,714 (-10%), face counts and
boundary-edge counts essentially unchanged on both, runtime negligible
(0.007s in isolation on the rack). This is the same function built (and
proven fast) during the abandoned pre-remesh-merge experiment — the slow
part of that experiment was `dissolve_faces` on huge clusters, not this
function, which is why it was safe to reuse here directly.

Caveat for future metric tracking: the stray-edge-fraction percentage can
go UP after a vertex-count-reducing cleanup like this even with zero
regression, because the denominator (total interior edges) shrinks. Track
the absolute stray-edge count alongside the percentage once a cleanup
stage like this is in the pipeline.

## Quadric-decimation fallback (new remesh.py capability)

`remesh.py` now has a third tier after Instant Meshes and quadriflow both
fail: `_try_decimate_fallback` (trimesh's `simplify_quadric_decimation`,
`fast-simplification` backend, explicit `aggression=5` — NOT the library
default, which was confirmed to silently create ~89 duplicate/degenerate
faces per ~97k that Blender's OBJ importer then drops on reimport,
producing invisible holes 2+ pipeline stages later). Targets the same
curvature-derived `target_faces_hint` sizing.py already computes. Real,
measured win on 000.glb: 61,383→31,746 final faces (-48%). Does NOT
replace field-aligned remeshing's QUALITY (not quad-dominant, no
anisotropic flow) — it's specifically a better substitute for raw
full-density passthrough when both real backends have already failed,
which per this session's testing is not rare (confirmed real crashes/
fragmentation on 000.glb's main body, dresser comp0003, and others).

Important finding from this investigation: quadriflow's failure on a
large/complex component is a genuine CRASH (`SIGABRT` via an internal
`assert()`, confirmed via a real macOS crash report), not a timeout —
raising `remesh.py`'s subprocess timeout would not fix this class of
failure. Separately, extensive Instant Meshes flag-tuning (no-`-d`,
no-`-b`, `-S 0`, intrinsic `-i`, `-r 6 -p 6`) on a different known-bad
component (dresser comp0003) found NO flag combination that avoids its
fragmentation bug — two variants (intrinsic mode, 6-fold symmetry) made it
measurably worse or hung entirely. Conclusion: these are real upstream
limitations of both third-party binaries on certain geometry classes, not
something fixable by adjusting how we call them.

**"Zipper" pattern investigated and closed as correct behavior, not a bug
(2026-11-02).** Initially assumed to be a fixable stitching/density-
mismatch seam needing a dedicated "crease-ribbon simplification" pass.
Investigated properly before building that:
1. Built a synthetic pure-density-mismatch zipper (two flat panels, a
   real crease, mismatched row density on each side) and confirmed the
   EXISTING `darts.py` + `coplanar_merge.py` + `dissolve_collinear_vertices`
   chain already resolves that case almost completely (80→22 faces,
   zigzag collapses to one clean region per side) — so that class of
   defect is already handled, no new tool needed for it.
2. Measured the REAL failing region's actual dihedral angles directly
   (`trimesh.face_adjacency_angles`): 84% of adjacent face pairs exceed
   the 2° coplanar-merge threshold, 44% exceed the real 18° crease
   threshold, median 13.5°. This is genuinely rough carved surface detail
   (a valley between decorative floral cells on this specific ornate
   asset), not a flat-panel stitching artifact.
3. **Decision (confirmed with the user): no further fix appropriate.**
   Smoothing this away would mean discarding real geometric detail,
   directly violating the Primary objective's zero-feature-loss
   constraint. The "messy" wireframe appearance here is the asset's actual
   geometry, correctly preserved — closed, not pursued further.

Lesson for this project: always measure the actual local geometry (angles,
not just the visual impression from a wireframe render) before building a
new simplification technique — a pattern that LOOKS like an artifact in
wireframe can be genuine, correctly-preserved detail, and the fix for a
synthetic/assumed version of a defect does not automatically generalize to
every instance that looks visually similar.

## Log

- 2026-11-01: T0 complete. `config.py` resolves Blender 5.2.3, Instant
  Meshes (found at a non-standard path under Downloads, CLI-tested
  working), and `bin/quadriflow`. `DEFAULT_REMESH_BACKEND = instant_meshes`.
- 2026-11-01: T1 complete. `io_blender.py` verified against the reference
  stats table exactly (dresser 81.58%/36 islands, robot 65.2%/88, dragon
  89.3%/4).
- 2026-11-01: T2 complete. `curvature.py` — confirmed Blender's bundled
  python (3.13, under `/Applications/Blender.app/.../Resources/5.2/python`)
  has neither `igl` nor `trimesh`; curvature always runs as a separate
  system-python3 subprocess. `igl.principal_curvature(V, F, radius, useKring)`
  returns `(PD1, PD2, PV1, PV2, bad_vertices)` — 5 values, not 4 as first
  assumed; `F` must be `int64`. `kappa = max(|PV1|, |PV2|)` used as the
  dominant curvature magnitude feeding `sizing.py`'s `h ∝ sqrt(eps/kappa)`.
  Verified visually on jade_sword.glb and the Tripo robot.

- **`core/fix_winding.py`** (new 2026-11-02): BMesh-native winding-
  consistency repair, run in `finalize_component.py` right after
  `caps.py`. Needed because `caps.py`'s new bevel-ring/chord-strip faces
  aren't guaranteed to match the surrounding mesh's winding, and a plain
  `bmesh.ops.recalc_face_normals` call doesn't fix it on a mesh with
  non-manifold edges (confirmed on a real decimation-fallback component).
  Deliberately NOT implemented via `trimesh.repair.fix_winding` — that
  only operates on `trimesh.Trimesh`, which stores triangles only, so
  loading/re-exporting through it would force full triangulation and
  destroy every quad/n-gon `coplanar_merge`/`darts`/`caps` already built.
  Algorithm: BFS edge-direction-comparison flood fill (same idea as
  trimesh's own repair), propagating through any edge with >=2 linked
  faces (not just exactly 2, needed to keep the traversal graph connected
  on a mesh with non-manifold edges), implemented as a pure decision pass
  (dict, zero mutation) followed by exactly one batched
  `bmesh.ops.reverse_faces` call — mutating bmesh connectivity mid-
  traversal was tried first and hung indefinitely. Caches each face's
  vertex→index map (`vert_index_cache`) since faces up to 45-sided appear
  in real output. Known limitation, not a bug: a tiny residual (~0.02-
  0.04% of faces, measured two independent ways) can remain on a mesh
  with genuine non-manifold defects from upstream decimation — a true
  non-manifold junction has no single globally "correct" winding, so this
  is a bounded best effort, not a claim of full global consistency.

- **`core/subdivide_mesh.py`** (new 2026-11-02): plain bmesh
  `subdivide_edges` (uniform, `use_grid_fill=True`) run under Blender,
  used ONLY by `pipeline.py`'s optional hard output-face-band enforcement
  (`_enforce_output_face_band`) to raise a final asset's face count up to
  a user-mandated floor. Confirmed quad-preserving in practice (a quad
  subdivides into 4 quads), unlike the decimation path used for the
  opposite (ceiling) direction. Not a quality improvement — it's a
  last-resort density topper for when the curvature-adaptive pipeline's
  own minimal, feature-preserving result is (correctly, by design) below
  a user-imposed floor.
- **`pipeline.py`'s `_enforce_output_face_band`** (new 2026-11-02):
  opt-in hard post-process guarantee that the final joined asset's face
  count lands inside `[min_output_frac, max_output_frac] * total_input_faces`.
  Subdivides up via `subdivide_mesh.py` first (quad-preserving, tried
  alone first since it's often already sufficient); only falls back to
  `remesh._try_decimate_fallback` (quadric decimation, fully
  triangulates) if subdividing overshoots the ceiling, or the asset
  started above the ceiling. Distinct from `sizing.py`'s
  `apply_face_budget` (the pre-finalize remesh-target hint band, a soft
  shaping input that does NOT guarantee the final count) — both are
  driven by the same `min_budget_frac`/`max_budget_frac` CLI args for
  convenience, but only the post-join enforcement is an actual guarantee.
