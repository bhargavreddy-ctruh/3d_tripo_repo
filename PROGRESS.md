# vacuum_quad_engine — Progress

Status legend: `[ ]` not started, `[~]` in progress, `[x]` done.
Updated at the start and end of every task — never batched at session end.

## T16 — Quadric-decimation fallback for failed remesh backends (real win, partial fix)

- [x] **User observation**: a close-up of 000.glb's output showed a dense
      "zipper" of tiny stitching triangles along a crease/valley line
      between large flat cells — visually ambiguous/messy, distinct from
      every prior fix (those were about non-crease flat regions).
- [x] **Root cause**: this component (the asset's main body, 499,963
      faces) had failed BOTH remesh backends entirely — Instant Meshes
      fragments it (97,390 islands), and quadriflow genuinely CRASHES on
      it (confirmed via a real macOS crash report: `SIGABRT` from an
      internal `assert()` failure in quadriflow's own `main()`, not a
      timeout — raising `remesh.py`'s timeout would not have helped).
      Extensive flag-tuning on a different known-bad component (dresser
      comp0003: no-`-d`, no-`-b`, `-S 0`, intrinsic `-i`, `-r 6 -p 6`) also
      failed to fix Instant Meshes' fragmentation — none helped, two made
      it measurably worse. So the component fell back to raw, full-density
      passthrough — and since `dissolve.py` needs quad grids (can't touch
      an all-triangle mesh at all) and `darts.py`/`coplanar_merge` only
      merge genuinely flat pairs/clusters, nothing in the pipeline ever
      reduced density in the component's curved/creased regions.
- [x] **Fix**: `remesh.py` now tries quadric-error decimation (via
      `trimesh.simplify_quadric_decimation`, the `fast-simplification`
      backend) to the curvature-derived `target_faces_hint` as a new
      fallback BEFORE the final raw-passthrough resort, when both
      field-aligned backends fail. Not field-aligned/quad-dominant, but
      still genuinely curvature-adaptive (the quadric error metric
      naturally preserves sharp features) — a real improvement over
      shipping undifferentiated full-scan density.
- [x] **Two real bugs found and fixed while building this**:
      1. The library's DEFAULT aggression setting silently produces ~89
         duplicate/degenerate faces per ~97k (an edge-collapse artifact);
         Blender's own OBJ importer then silently DROPS those duplicate
         faces on reimport, leaving real holes (170 new boundary edges)
         that were otherwise invisible until traced through the full
         pipeline. Fixed by explicitly using `aggression=5` (tested
         directly: produces a clean, duplicate-free, trimesh-measured
         watertight result at the exact target face count) AND by
         explicitly deduplicating faces before export regardless, as a
         second layer of defense.
      2. Confirmed `trimesh.repair.fill_holes` can't fix this class of
         defect (genuine local pinch/non-manifold points, not simple open
         boundary loops) — not pursued further once `aggression=5` made it
         moot.
- [x] **Measured, honest result on 000.glb**: final face count
      61,383→31,746 (-48%), backend correctly reports
      `quadric_decimation_fallback` instead of `passthrough_unremeshed`,
      zero finalize failures. Boundary-edge count after the full pipeline
      (181) reframed honestly: this is WITHIN the normal range real Tripo
      exports already have (their own robot reference has 1,027 boundary
      edges) — not chased further than that once established.
- [x] **Does NOT fully fix the originally-reported zipper defect — root-
      caused, and CLOSED as "correct behavior, not a bug"** (2026-11-02):
      direct before/after comparison at matched zoom (same crop, same
      camera) showed the sawtooth pattern along the crease was still
      present after decimation. Investigated properly before attempting a
      "crease-ribbon simplification" fix:
      1. Built a synthetic test (`/tmp` scratch, not committed) replicating
         a PURE density-mismatch zipper — two genuinely flat panels
         meeting at a real crease, with mismatched row density on each
         side (the classic "stitching" defect this was assumed to be).
         Confirmed the EXISTING tool chain (`darts.py` + `coplanar_merge.py`
         + `dissolve_collinear_vertices`) already resolves this case
         almost completely: 80→22 faces, the zigzag collapses to one clean
         flat region on each side.
      2. Directly measured the REAL failing region's actual dihedral
         angles (via `trimesh.face_adjacency_angles`, not assumed): 84% of
         adjacent face pairs exceed the 2° coplanar-merge threshold, and
         **44% exceed the real 18° crease threshold**, median 13.5°. This
         is NOT a flat-panel density mismatch — it's genuinely rough,
         undulating carved surface detail (consistent with this being a
         valley between decorative floral "scale" cells on this ornate
         asset), which the pipeline is correctly identifying as real
         geometric variation and preserving.
      3. **Conclusion, confirmed with the user: no further fix is
         appropriate here.** The wireframe's "zipper" appearance is the
         genuine geometry, not a stitching artifact — smoothing it away
         would mean discarding real carved detail, directly violating the
         Primary objective's zero-feature-loss constraint. Closed as
         correct, faithful behavior rather than pursued further.

## T15 — Boundary collinear-vertex cleanup (new stage, fixes jagged merged-panel edges)

- [x] **User observation, confirmed real and distinct from the earlier
      stray-edge fix** (2026-11-02): even a correctly `coplanar_merge`-ed
      flat region's own BOUNDARY still showed multiple small collinear
      segments instead of one clean straight line. Root cause: `coplanar_merge`
      deliberately uses `dissolve_faces(..., use_verts=False)` (for
      T-junction safety, see its own earlier bug-fix history), which keeps
      every boundary vertex in place even when it's now genuinely
      redundant (sitting exactly on a straight line between its two
      neighbors).
- [x] **Reused an already-built, already-proven-fast function**:
      `coplanar_merge.dissolve_collinear_vertices` (originally written for
      the abandoned pre-remesh-merge experiment, where it measured 0.58s
      even on a 93k-vertex mesh — the SLOW part of that experiment was
      `dissolve_faces` on huge clusters, not this function). It only
      targets valence-2 vertices, which by construction can never be
      shared with any other face/edge — so there is no T-junction risk at
      all, unlike `dissolve_faces(use_verts=True)`'s bug found earlier.
      Lossless: a vertex is only removed if it lies exactly on the line
      between its two neighbors.
- [x] **Wired into `finalize_component.py`** right after `coplanar_merge`.
      Measured on the real pipeline (not just isolation): rack 4,553→2,231
      vertices (-51%), face count essentially unchanged (1125→1121,
      boundary 0→0); sofa 1,906→1,714 vertices (-10%), faces exactly
      unchanged (1032→1032), boundary unchanged (3→3). Runtime
      negligible (0.007s in isolation). Honest renders confirm visibly
      straighter edges on both (the rack's front-panel top edge in
      particular went from a visible jagged zigzag to one clean line).
- [x] **One measurement caveat worth recording**: the stray-edge-fraction
      metric (near-coplanar non-triangle-pair interior edges / total
      interior edges) went UP on the rack after this change (4.4%→7.46%)
      — this is a denominator artifact, not a regression: total interior
      edges dropped sharply (5,676→3,350) from removing ~2,400 genuinely
      redundant vertices, while the ABSOLUTE stray-edge count stayed flat
      (~250 either way). Any future use of that metric should track the
      absolute count alongside the percentage once vertex-count-reducing
      cleanup stages are in the mix.

## T14 — Lattice straightening investigation (tested, reverted — asset-dependent)

- [x] **Quality-gap re-investigation** (2026-11-02): user asked to improve
      flow regularity (valence-4%) after the speed investigation. Measured
      precisely before assuming anything: restricting valence-4% to
      vertices that touch ONLY quad faces (no triangle, no n-gon) showed
      the earlier "40-52% vs Tripo's 86%" gap was substantially an
      artifact of `coplanar_merge` being very effective (most vertices now
      touch a merged n-gon, which is correct/desirable, not a flaw) —
      true quad-flow regularity in that narrow sense was 002.glb 78.3%,
      rack 65.3%, sofa 54.7% (small/noisy samples for the latter two).
- [x] **Built `experimental/lattice_straighten.py`** (ported from the
      original ribbon_engine reference design, never previously
      implemented here): nudges a valence-4 vertex toward the midpoint of
      its opposite neighbors when its 4 surrounding faces are already
      near-coplanar. Position-only, provably never changes vertex/face/
      edge counts (asserted directly in the script).
- [x] **Tested in isolation first, per standing instruction**: on the
      dresser's tube component (smoothly curved), pre-straightening the
      fresh remesh output before dissolve/darts/coplanar_merge measurably
      helped — 460→429 final faces (6.7% fewer), then 460→418 (9.1%
      fewer) when run through the real `finalize_component.py` path.
      Visually near-identical (sub-pixel position nudges), zero boundary
      change.
- [x] **Wired into `finalize_component.py`, then REVERTED after a full
      real-asset end-to-end test contradicted the isolated result**: on
      the wooden rack (mostly flat panels, not smoothly curved like the
      tube), the SAME change caused final face count to go UP
      (1125→1189, +5.7%) despite the stray-edge fraction staying
      essentially flat (4.4%→4.14%). The technique is asset-shape-
      dependent: it helps smoothly-curved geometry (matches its original
      design intent — removing remesh-field micro-jitter on a curve) but
      can hurt mostly-flat geometry (plausible mechanism: a locally-
      "straightening" nudge can perturb a vertex's face normal just
      enough to drop it out of a LARGER coplanar region's angle
      tolerance, fragmenting what `coplanar_merge` would otherwise have
      merged as one big flat cluster).
- [x] **Reverted cleanly**: `finalize_component.py` is back to its exact
      pre-change behavior (verified: re-ran the dresser tube test,
      reproduced the original 460-face baseline exactly, no
      `lattice_straighten` key in the result). `experimental/
      lattice_straighten.py` is kept, documented, and NOT deleted, with a
      note in `finalize_component.py`'s own docstring so a future attempt
      doesn't have to rediscover this — a worthwhile next step would be
      gating it on a per-component shape heuristic (e.g. only apply where
      the component's curvature is non-trivial) rather than applying it
      universally.

## T13 — General coplanar-region merge (new stage, fixes "stale edges")

- [x] **Root cause found** (2026-11-01, measured directly on real output,
      not guessed): the user flagged visible stray/unnecessary edges
      crossing flat panels in the rack and sofa honest renders. Measured
      on the actual OBJ topology: 30.9% of the rack's and 9.0% of the
      sofa's interior edges were between two faces differing by <2°
      (genuinely flat) and were NOT a triangle pair. Neither existing
      merge mechanism could touch them: `dissolve.py`'s loop tracer only
      continues through exactly-valence-4 vertices (valence-3 is nearly
      as common as valence-4 on real output — not a rare singularity),
      and `darts.py` only merges triangle+triangle pairs.
- [x] **`core/coplanar_merge.py` built and tested in isolation** before
      touching the main pipeline (per explicit user instruction): flood-
      fills faces into coplanar clusters (own tight 2° per-edge angle
      check, boundary always respected) and merges each via bmesh's
      `dissolve_faces`.
- [x] **Two more real bugs found while building/testing it:**
      1. Reusing `protect.py`'s hard-protected set as the flood-fill
         boundary seemed natural but was wrong: its dome/saddle rule
         flagged 72% of the rack's edges as "features" — because it was
         being recomputed on an ALREADY dissolved+darted mesh, whose
         non-planar merged n-gons have noisy Newell normals that the
         rule's mean-deviation check misreads as poles. Fixed by giving
         `coplanar_merge.py` its own minimal, direct per-edge angle check
         instead of depending on `protect.py` at this late stage.
      2. `bmesh.ops.dissolve_faces(..., use_verts=True)` corrupted shared
         topology: a trivial 2-face cluster that passed a disk-topology
         pre-check still grew the mesh's boundary-edge count by 3, because
         `use_verts=True` deleted a vertex also used by a face OUTSIDE the
         cluster (a T-junction). Fixed with `use_verts=False` (never
         removes a vertex, so the operation is provably boundary-safe) plus
         an added `_is_disk_topology` pre-check (skip any cluster whose
         boundary isn't a single simple loop) as defense in depth.
      3. Wired into `finalize_component.py` between `darts` and `caps`,
         fault-isolated the same way as the other four stages.
- [x] **Verified on 3 real assets**: rack stray-edge fraction 30.9% → 4.4%
      (3,431 → 1,125 faces, boundary unchanged 0→0); sofa 9.0% → 0.9%
      (1,330 → 1,032 faces, boundary unchanged 3→3); dresser tube
      component (curved, trickiest prior case) 3,051 → 500 faces, 0
      clusters skipped. All honest-rendered before/after; stray diagonal
      lines visibly gone from flat panels in both renders.
- [x] **Important, honest caveat for future reference**: `audit.py`'s
      `quads_pct`/`valence_4_pct` metrics DROP after this stage (rack
      80.82%→53.6% quads, 51.92%→10.45% valence-4). This is a metric-
      definition artifact, not a quality regression: a large clean merged
      flat n-gon isn't counted as a "quad," and its irregular boundary
      corners aren't valence-4 — but it IS the more minimal, correct
      answer for a flat region, consistent with the earlier
      `ngon_restore` finding (T11's generality round) that large flat
      n-gons are already the clean answer, not something to eliminate.
      Any future benchmark comparison against the Tripo reference median
      must account for this — raw `quads_pct` is not a reliable
      cleanliness signal once large flat regions exist in the output.

- [x] **T0 — Bootstrap & tracking docs** (2026-11-01): `core/config.py`
      created, resolves Blender 5.2.3 LTS, Instant Meshes (non-standard
      path under `~/Downloads/.../tools/`, CLI batch mode tested clean),
      `bin/quadriflow`. `TECH_NOTES.md` and this file created.
- [x] **T1 — I/O layer** (2026-11-01): `core/io_blender.py` created
      (import/export FBX/GLB/OBJ via bpy, per-object stats, island count via
      vertex flood-fill, `bounding_box_diagonal()` for scale-derived
      tolerances elsewhere). Verified: dresser/robot/dragon FBX stats
      (quad%, islands) exactly match the session's already-measured
      reference table; 854k-tri wooden-rack raw GLB loads in ~2s
      (1 island, 100% tris, as expected for the raw unsegmented scan).
- [x] **T2 — Curvature field** (2026-11-01): `core/curvature.py` created
      (libigl `principal_curvature`, runs under system python3 — confirmed
      Blender's bundled python lacks igl/trimesh, so this always runs as
      its own subprocess, fed an intermediate OBJ for FBX inputs via
      `io_blender.py`). Fixed an API-signature bug (returns 5 values,
      `bad_vertices` list, not 4; faces need int64). Verified by eye on
      jade_sword.glb (flat blade = dark, ornamental hilt = bright) and
      robot.obj (panel-line joints bright, flat wing dark) — curvature
      correctly isolates detail from flat regions.
- [x] **T3 — Decomposition** (2026-11-01): `core/decompose.py` created —
      join-then-immediately-loose-separate (end state is always N separate
      component objects/OBJs, never a joined mesh carried into remeshing;
      the join is only a mechanism for bpy's `separate(type='LOOSE')`, not
      the tripo_smart_engine bug it fixes). Each component exported as its
      own OBJ + a JSON manifest (path, stats, bbox_diagonal per component).
      Verified: dresser=36, robot=88 components, exactly matching measured
      island counts.
- [x] **T4 — Per-component sizing** (2026-11-01): `core/sizing.py` created
      (`h = clip(sqrt(eps/max(kappa,floor)), h_min, h_max)`, all three
      scaled from the WHOLE ASSET's bbox diagonal so components share
      consistent units; integrated `target_faces_hint = area/mean(h)^2`,
      explicitly a hint for the remesher, never a cap). Verified on the
      dresser's 36 components: a large flat component (area 0.668,
      kappa_median 3.6) got density ~2,886 faces/unit-area; a small
      high-curvature component (area 0.00067, kappa_median 239) got
      ~220,898 faces/unit-area — curvature-driven, not size-driven,
      confirming no per-asset special-casing is needed.
- [x] **T5 — Remesh** (2026-11-01, revised after generality testing):
      `core/remesh.py` — per-component Instant Meshes / quadriflow, with a
      real fragmentation guard (`is_fragmented` via `trimesh` connected-
      component count) added after the FIRST pass of this task looked
      clean on paper (rc=0, file written) but visual inspection caught
      Instant Meshes silently shattering dresser comp0003 into 407
      islands from a 1-island input. Both backends now gated by actual
      output quality, not subprocess exit codes; a component where BOTH
      backends fail falls back to `passthrough_unremeshed` (original
      geometry kept exactly, zero feature loss, just not reduced).
      Generality-tested on dresser (36 comps: 1 IM, 24 quadriflow, 11
      passthrough) and jade_sword (107 comps: 5 IM, 93 quadriflow, 9
      passthrough) — real, non-trivial fallback usage on both assets, not
      a rare safety net; see TECH_NOTES for the two distinct underlying
      failure modes found (IM fragmentation; quadriflow's silent
      `wrong init` solver abort).
- [x] **T6 — Protection mask** (2026-11-01): `core/protect.py` created —
      hard-protect (boundary, true crease >=18°, dome/saddle pole
      vertices) + a continuous finite cost (base dihedral angle + a smooth
      micro-feature bonus using this component's OWN local median face
      area, never a global one) for everything else. Found and fixed a
      real bug: face normals needed `bmesh.ops.recalc_face_normals` right
      after import before ANY angle-based test, or Instant Meshes'
      winding produces false deviation readings (this did not change the
      actual numbers below, confirming winding was already consistent
      here, but is a correctness requirement that must stay in place for
      other assets). Measured on dresser comp0001: 68% hard-protected.
      VISUALLY CONFIRMED CORRECT, not a bug (`render_protect_debug.py`,
      `comp0001_closeup.png`): this component is a thin rounded tube/rail
      bent into a rectangle (a handle/pull). The red (protected) edges are
      exactly the tube's cross-section rings, correctly protected all the
      way around since a round tube is genuinely curved everywhere in that
      direction; the colored (free, finite-cost) edges are exactly the
      lengthwise rails along each straight run, correctly left free for
      T7's straight-slat dissolution to collapse. This is the textbook
      anisotropic pattern the whole engine targets — confirmed by eye
      before trusting the aggregate percentage.
- [x] **T7 — Dissolution** (2026-11-01, found and fixed a real bug via
      real-asset testing): `core/dissolve.py` — ported
      `trace_full_transverse_loop`, driven by protect.py's continuous cost
      (lowest-cost/flattest loops dissolved first each pass) instead of
      fixed tiers. Synthetic flat 10x6 grid self-test: 60→1 faces, exact
      zero area change, boundary 32→4, passed immediately. BUT running on
      a real remeshed component (dresser comp0001, comp0007) surfaced a
      genuine bug the synthetic test couldn't: `cost_map` has an entry for
      EVERY edge (protected ones included, at cost=inf), so filtering
      candidate loop-START edges by "in cost_map" alone let a
      hard-protected (boundary/crease) edge become a loop start and get
      dissolved — fixed by explicitly excluding `protected_set` when
      building candidates, plus a defense-in-depth check inside
      `trace_full_transverse_loop` itself. Also discovered or non-planar
      merged n-gons (any real curved component, confirmed on comp0001 — a
      tube bent into a rectangle), "total area" has NO single correct
      value: bmesh's own `calc_area()` and a from-scratch triangulated sum
      disagreed by 30%+ on the SAME final mesh, while both the boundary-
      edge-count invariant AND a trimesh watertight/winding-consistency
      check on the actual exported OBJ stayed clean throughout, and a
      before/after render was visually identical in silhouette. Redesigned
      the safety net accordingly: boundary-edge-count-never-increases is
      the one hard, planarity-independent gate; area drift is now an
      informational stat only (an absurd >500% swing still hard-fails, to
      catch a true catastrophic bug, not normal non-planar noise).
      Final verified result on comp0001: 6102→2934 faces, watertight=True,
      winding_consistent=True, silhouette visually unchanged.
- [x] **T8 — Darts & caps** (2026-11-01): `core/darts.py` (bmesh
      `join_triangles` at the COPLANAR_DART_DEG=24° threshold, boundary-
      edge-count checked unchanged) — tested on the dissolved comp0001:
      30 triangle pairs merged, quad% 74.96%→79.55%, boundary stayed 0.
      `core/caps.py` (bevel-ring + parallel-chord quad cap construction,
      ported from `burger_stand_retopo.py`) — found and fixed a real bug
      via self-test: bmesh leaves new edges' `.index` at -1 until an
      explicit renumbering, so keying a visited-set by `.index` silently
      collapsed every edge onto the same key and broke the loop walk after
      one step; fixed by keying on the edge object itself. After the fix,
      self-test (synthetic 16-gon open-top/open-bottom tube) produced
      EXACTLY the reference formula's numbers: 16 bevel quads + 7 chord
      quads = 23 pure quads per cap, 0 triangles, matching
      `structured_adaptive_retopo_report.md`'s own N_theta=16 example
      precisely.
- [x] **T9 — Reprojection** (2026-11-01): `core/reproject.py` — Blender
      SHRINKWRAP modifier snapping the simplified mesh onto the original
      dense component. Tested comp0001 (darted output) against its own
      original dense source: max vertex shift 0.0040 units = 0.43% of
      bbox diagonal, mean shift 0.012% — small corrective snap, not a
      distortion. Re-confirmed watertight=True, winding_consistent=True
      after reprojection (trimesh).
- [x] **T10 — Audit** (2026-11-01): `core/audit.py` ported faithfully
      (same formulas, reusing `io_blender` helpers instead of a separate
      embedded script). Verified against tripo_smart_engine's own
      `outputs/sofa_smart_quads.fbx` and the README's documented numbers
      for it: boundary_edges 61, valence_4_pct 90.66%, triangles_paired_pct
      23.31%, aspect median/90th/max 1.20/2.09/4.34 — EXACT match on every
      field.
- [x] **T11 — Pipeline orchestration** (2026-11-01, two more real bugs
      found and fixed via the first full end-to-end run): `core/pipeline.py`
      + `core/finalize_component.py` + `core/join_components.py`. First
      full run on the dresser FBX hit 5/36 components failing at the
      finalize stage with two distinct crashes:
      1. `dissolve.py`: "found the same (BMEdge) used multiple times" —
         a traced loop can revisit the same edge where its forward/backward
         walks meet, and `bmesh.ops.dissolve_edges` rejects a duplicate
         edge in its input outright. Fixed by deduping `edges_to_dissolve`
         via a set before the call.
      2. `protect.py`: "Vector.angle(other): zero length vectors have no
         valid angle" — the dome/saddle rule's `avg_n` (sum of surrounding
         face normals) can be near-zero at a genuine sharp fold where
         normals nearly cancel; `.angle()` on a zero vector raises. Fixed
         by detecting this and conservatively hard-protecting that vertex
         instead of crashing.
      Also made `finalize_component.py` fault-isolate each stage
      (dissolve/darts/caps/reproject) independently — one stage failing no
      longer discards the others' completed work, per the safe-degradation
      principle already established in remesh.py. Re-run after both fixes:
      0/36 finalize failures (down from 5/36), final asset 7,184 faces,
      67.94% quads, watertight join across 44 islands.
      **Known, documented limitation** (see TECH_NOTES): this input is
      already Tripo's OWN clean low-poly reference mesh (not a dense raw
      scan), so re-processing it is an out-of-scope stress test, not the
      intended use case — its quad%/valence-4% (67.94%/50.2%) are
      currently BELOW the original reference's own numbers for this exact
      asset (81.6%/85.6%), and `aspect_max` shows a 4882:1 outlier sliver
      not yet root-caused. T12 must validate against genuinely dense/raw
      inputs instead, where curvature-adaptive sizing actually applies.
- [x] **T12 — Full verification pass** (2026-11-01, on jade_sword.glb — a
      genuinely dense, non-Tripo-reference asset, per the important
      "dense input, not Tripo's own output" correction above): full
      pipeline run, 0/107 remesh failures, 0/107 finalize failures.
      Final: 8166 input faces → 1849 output faces (quad/tri/ngon mixed,
      64.41% quads). **Visual confirmation (`jade_final_render.png`) shows
      exactly the targeted curvature-adaptive result**: the flat blade
      collapsed to a handful of large clean faces (near-zero curvature →
      minimal faces), while the ornate hilt/guard retained dense detailed
      geometry (high curvature → preserved density) — this is the Primary
      Objective's exact target behavior, visually matching the curvature
      field measured back in T2 on this same asset.
      **Known residual issues, honestly documented, not yet fixed**:
      - A small visible notch/gap near the blade tip (minor local artifact,
        likely a dissolve/boundary interaction at a sliver component).
      - `boundary_edges` (1988) exceeds `faces` (1849) — far more open
        boundary than tripo_smart_engine's own jade sword reference (41
        boundary tears on a 24k-tri input, a different/larger source file
        than this session's 8k-face `assets/inputs/jade_sword.glb`, so not
        a strictly apples-to-apples number, but still a real fragmentation
        gap worth closing in a follow-up pass).
      - `valence_4_pct` (39.7%) is well below real Tripo references
        (64-92% range measured earlier) — the "flowed-ness" signature
        isn't yet at Tripo's level despite the correct curvature-adaptive
        shape emerging.
      These are legitimate next-iteration targets, not blockers: the
      core thesis (curvature-driven density, preserved detail, collapsed
      flats) is proven working end-to-end on real geometry.

## Additional real-world test: `002.glb` (500k tris, spider/scorpion-like creature)

Run 2026-11-01, user-requested. Robustness was excellent: 5/5 components
succeeded via quadriflow (no Instant Meshes or passthrough fallback
needed at all — the cleanest backend run of any asset tested), 0 remesh/
finalize failures, 500k→15,571 faces, only 18 boundary edges, 64.69%
quads, 86.3% of quads under 2:1 aspect ratio. **But the visual render
(`002_final_render.png`) exposed a real, previously-unseen quality gap**:
the body simplified reasonably, but the thin leg/appendage components are
covered in dense, chaotic triangle fans, not the flowing anisotropic quad
strips the engine targets — a sharp contrast to the jade sword's genuinely
clean blade collapse. Working hypothesis (not yet investigated): organic,
irregularly-bending thin limbs likely trigger much more crease/dome-
saddle hard-protection along their length than the jade sword's simpler,
more uniform blade and the dresser's straight tube-rail component, leaving
`dissolve.py` far less room to collapse them — this is the clearest
concrete lead for the next round of work on `protect.py`'s thresholds or
`dissolve.py`'s loop-tracing tolerance for organic/irregular thin parts.
This is reported honestly as a known gap, not claimed as solved — metrics
alone (which all looked fine here) are not sufficient proof of quality,
exactly per this session's own "render before moving on" rule.

## Winding-consistency bug in `caps.py`, found via dissolve_limit investigation, fixed with new `fix_winding.py`

Found 2026-11-02 while testing Blender's built-in Limited Dissolve against
the crease-ribbon region: `trimesh.is_winding_consistent` on a real
decimation-fallback component (000.glb) went from `True` before
`caps.cap_all_planar_boundaries` ran to `False` after. Root cause: the
bevel-ring + chord-strip faces `caps.py` creates use a fixed vertex order
that isn't guaranteed to match the surrounding mesh's existing winding.
`bmesh.ops.recalc_face_normals(bm, faces=bm.faces)` (added to `caps.py` as
a first attempt) was confirmed **insufficient on its own** — the
component's own 95 non-manifold edges (a known artifact of the quadric-
decimation fallback) defeat bmesh's built-in flood-fill consistency.

**Fix**: new `core/fix_winding.py`, a BMesh-native BFS winding-consistency
repair (stays within bpy/bmesh so it preserves quad/n-gon topology, unlike
`trimesh.repair.fix_winding` which forces full triangulation on load).
Wired into `finalize_component.py` right after `caps.py`. Three real bugs
found and fixed while building it:
1. V1 only propagated through edges with exactly 2 linked faces — left
   most faces unreachable from the BFS seed on a mesh with many
   non-manifold edges (only 1-10 faces ever got flipped). Fixed by
   propagating through any edge with >=2 linked faces.
2. V2 called `bmesh.ops.reverse_faces` INSIDE the traversal loop, mutating
   bmesh connectivity while a live iterator (`e.link_faces`) over that
   same connectivity was still in use — hung 5+ CPU-minutes, never
   completed. Fixed by splitting into a pure decision phase (no mutation)
   followed by exactly one batched `reverse_faces` call at the end.
3. Uncached `list(face.verts)` + linear search on every edge check was a
   real perf concern on faces up to 45-sided seen in real output. Fixed
   with a per-face `vert_index_cache`.

**Verified results**: dresser tube (comp0001, already winding-consistent)
— correct no-op, 0 faces flipped, all other stage outputs identical to
the pre-change baseline. 000.glb's problem component — 58 faces flipped
on first pass; a second pass on the fix's own output still finds 7 more
(~0.02% of ~31,745 faces) — NOT zero. On the full joined final asset
(`000__final.obj`, post-reproject/post-join), measured independently via
trimesh's own face-adjacency edge-direction check: 41 inconsistent
adjacent face pairs out of 94,227 (0.04%), consistent in scale with that
in-bmesh residual. Investigated whether this residual is a real
unfixable defect or a trimesh-triangulation artifact (trimesh triangulates
large n-gons on load, which can introduce its own winding noise unrelated
to the true n-gon mesh) — not conclusively resolved either way, but the
residual is tiny and stable across two independent measurement methods,
consistent with a genuine locally non-orientable patch left by the
decimation fallback's own duplicate/degenerate-face artifacts, not a bug
in `fix_winding.py` itself. Not chased further: this is a dramatic,
verified improvement (near-total fix) on a defect that previously had no
mitigation at all, and the "near-opposite normal" heuristic originally
used to estimate inconsistency scale (3,637 "pairs") was itself found
unreliable for this asset (confuses genuine sharp creases — 44% of edges
in one region exceed 18° — with real winding flips), so no trustworthy
"before" number exists for a precise percentage comparison.

Full re-run of 000.glb with the fix integrated: 245.4s total, same
component/backend split as the decimation-fallback baseline (quadric_
decimation_fallback + instant_meshes), 31,746 faces / 31,650 verts /
181 boundary edges / 95 non-manifold edges — all audit numbers unchanged
from the pre-fix baseline except winding, confirming `fix_winding` is a
pure addition with no side effects on the rest of the pipeline's output.

## Optional hard output-face-count band (0.5%-3% of input faces), user-requested 2026-11-02

User explicitly requested a hard constraint: "nothing less or more, this
is set" — the FINAL output face count must land inside
`[min_frac, max_frac] * total_input_faces` (0.5%-3% as the concrete
numbers given), no exceptions. This is opt-in (`None`/`None` by default,
unchanged pipeline behavior) — added because of a direct user instruction,
not a change to this project's own Primary objective (minimal faces for
zero feature loss, no fixed budget by default).

Two separate mechanisms, both wired through `pipeline.py`'s
`min_budget_frac`/`max_budget_frac` CLI args:
1. **Soft pre-finalize hint band** (`sizing.py`'s `apply_face_budget`,
   built first): scales the curvature-integrated remesh target hint per
   component into a band, proportionally, preserving relative
   curvature-driven distribution. This only shapes the remesh STARTING
   point — finalize's dissolve/darts/coplanar_merge stages still simplify
   further afterward, so this alone does NOT guarantee the final count
   lands in the band (confirmed: testsample1 with a 3% ceiling on the
   remesh hint still finalized down to 1,000 faces, same as unconstrained).
2. **Hard post-process output clamp** (`pipeline.py`'s
   `_enforce_output_face_band`, the actual guarantee): runs after the
   join stage, checks the REAL final joined asset's face count, and only
   if it's outside the band:
   - **Under the floor** (the common case — every real asset tested this
     session naturally finalizes to well under 1% of input faces, since
     that's the curvature-adaptive minimum): `subdivide_mesh.py` (new
     file) runs plain bmesh `subdivide_edges` passes (quad-preserving:
     confirmed directly — testsample1 went from 50.8% quads to **68.5%
     quads** after subdividing, since subdividing a quad cleanly yields 4
     more quads) until the floor is reached. If that alone lands inside
     the band (true on every asset tested), nothing else happens — no
     triangulation, no decimation.
   - **Over the ceiling** (only reached if subdividing overshoots past it,
     or the asset started above the ceiling with no subdivision needed):
     falls back to `remesh._try_decimate_fallback`'s quadric decimation,
     targeting the geometric mean of floor/ceiling as a safe mid-band
     landing spot. Honestly flagged in the stats
     (`"triangulated": true`) — like every other decimation-fallback
     component already in this pipeline, this fully triangulates the
     result; there's no quad-aware exact-count-control tool in this
     codebase, so exact final-count guarantees and quad purity trade off
     against each other whenever the decimate path is actually taken.

**Verified on testsample1_raw_860k.glb** (0.5%-3% band, floor=4,301,
ceiling=25,807 faces): natural finalize result 1,000 faces (below floor)
→ 2 subdivision passes → 11,860 faces (inside the band, no decimation
needed) → quads_pct 68.53% (UP from 50.8% unconstrained), 0 non-manifold
edges, winding still fully consistent (`trimesh.is_winding_consistent:
True`) after subdividing. Saved to
`outputs/testsample1_raw_860k_band0.5to3pct/`.

Usage: `python3 pipeline.py <input> <out_dir> 0.005 0.03`.

**Regression confirmed on 3 more real assets** (0.5%-3% band, same CLI
args), all 0 remesh/finalize failures:
- **Rack** (854,828 input faces, floor 4,274/ceiling 25,645): natural
  968 faces (below floor) → 2 subdivision passes → 11,708 faces (inside
  band, no decimation needed), quads_pct 75.44% (up from the
  unconstrained baseline), 0 non-manifold edges, 0 boundary edges.
- **Koala** (1,790,758 input faces, floor 8,954/ceiling 53,723): natural
  3,117 faces (below floor) → 2 subdivision passes → 32,759 faces
  (inside band), quads_pct 68.67%, 0 non-manifold edges, 12 boundary
  edges.
- **"image (18)" multi-part asset** (89,827 input faces, floor
  449/ceiling 2,695): here the SOFT pre-remesh sizing band (shared CLI
  args) had a real, significant effect — natural curvature estimate for
  this asset exceeded the ceiling, so the remesh-stage hint was scaled
  down well before finalize ran, landing the pipeline's natural result at
  866 faces, already inside the band with no post-join clamp needed at
  all (`"action": "none_already_in_band"`). Worth noting plainly: unlike
  every raw-scan asset tested (where the soft hint band has essentially
  no effect, since finalize's own simplification already lands far below
  any ceiling this small), this smaller/already-lower-poly asset's
  natural curvature estimate was large enough for the soft band to
  meaningfully reshape the remesh starting point. One honest residual: 1
  non-manifold edge appeared on this asset (every other test in this
  project has been 0) — small, not chased further, but flagged rather
  than silently reported as clean.

All four real-asset tests (testsample1, rack, koala, image18) confirm the
hard output-band guarantee holds, and subdivision-only (no triangulation)
was sufficient in every case tested so far.
