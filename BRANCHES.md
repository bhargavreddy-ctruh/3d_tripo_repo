# Branch Guide

This file documents every development branch in this repository — what each one tried, what it found, and whether it is still relevant. The **current production branch is `main`** (see below for how `field-aligned-merge-experiments` is merged into it).

---

## Branch Lineage (oldest → newest)

```
main  (original vacuum_quad_engine)
  └── use-bpy-module-in-process       [dead end — bpy still required Blender]
  └── no-blender-pure-python          [milestone: eliminated Blender entirely]
        └── proper-quads-full-lines   [experiment: strict full-line quad decimation]
        └── clean-generalized-pipeline [milestone: planar merge + structured topology]
              └── nondisk-planar-merge [experiment: multi-hole coplanar merge]
              └── field-aligned-merge-experiments [LATEST — dome/saddle caps added]
                    └── structured-coplanar-quad-strip [experiment: quad-strip engine]
                    └── percentage-budget              [experiment: 0.05-1% face budget]
```

---

## Branch Details

### `main` — Original baseline *(stale)*

**Status:** Stale. Contains only the original `vacuum_quad_engine` commit. The final production code has been merged here from `field-aligned-merge-experiments`.

**What it had:** Blender-based (`bpy`) curvature-adaptive retopology pipeline. Per-component decompose → size → remesh → dissolve loop in Blender's Python environment.

**Why it was replaced:** `bpy` pip wheel must match the installed Blender version exactly; pipeline start-up cost per stage was multi-second; no in-process mesh state sharing between stages.

---

### `use-bpy-module-in-process` — In-process bpy *(dead end)*

**Status:** Archived / dead end.

**What it tried:** Run Blender in-process via the `bpy` pip module instead of launching a `blender` subprocess per stage — eliminates the subprocess overhead while keeping all existing bmesh/bpy code unchanged.

**Why it failed:** The `bpy` pip wheel's version must exactly match the user's installed Blender desktop app, creating a maintenance burden. Any Blender update breaks the import. Decided to eliminate `bpy` entirely instead.

---

### `no-blender-pure-python` — Eliminate Blender *(milestone)*

**Status:** Superseded by `clean-generalized-pipeline` and later branches.

**What it achieved:**
- Rewrote `io_blender.py` → `io_mesh.py` (pure trimesh/OBJ)
- Replaced `bmesh` with `core/editmesh.py` — a mutable polygon mesh (verts/edges/faces + adjacency) that preserves quad/n-gon arity (unlike `trimesh.Trimesh`)
- Rewrote `dissolve.py`, `darts.py` to operate on `EditMesh` directly
- Fixed three bugs: broken fragmentation check, phantom island detection, bad coplanar merges

**Key insight:** "A fresh Blender scene" is now just a fresh `io_mesh.load()` call. No process, no overhead.

---

### `proper-quads-full-lines` — Strict full-line quad decimation *(experiment)*

**Status:** Superseded. Findings merged into `clean-generalized-pipeline`.

**What it tried:** Enforce that dissolution only collapses a full edge loop from boundary to boundary (or a closed ring), never an isolated interior edge. Prevents T-junctions.

**What it found:** Works well on flat/low-curvature regions. On curved organic surfaces, full-line tracing prematurely terminates at valence ≠ 4 vertices (valence-3 is as common as valence-4 on real remesher output), leaving redundant chord fragments.

---

### `clean-generalized-pipeline` — Structured planar merge *(milestone)*

**Status:** Superseded by `field-aligned-merge-experiments`.

**What it added over `no-blender-pure-python`:**
- `coplanar_merge.py` — general coplanar flood-fill merge that handles valence ≠ 4 vertices (the fix for `dissolve.py`'s valence-4-only loop tracer)
- Structured pipeline: darts → coplanar_merge → caps → fix_winding → reproject (instead of dissolve-first)
- Minimal-face objective: maximize face count reduction on flat surfaces while preserving all curvature features

**Key fix:** `dissolve.py`'s transverse-loop tracer only continued through exactly valence-4 vertices. Measurement showed valence-3 is nearly as common on real remesher output, so the tracer left most interior edges untouched. `coplanar_merge.py` uses a flood-fill approach instead, handling all valence values.

---

### `nondisk-planar-merge` — Multi-hole coplanar merge *(experiment)*

**Status:** Merged into `field-aligned-merge-experiments`.

**What it tried:** Extend `coplanar_merge.py` to correctly handle coplanar regions with holes (non-disk topology, e.g. a flat surface with a circular cutout). Pairwise approach: instead of one large n-gon per coplanar cluster, merge adjacent face pairs iteratively — produces only 4-to-6-gon intermediates rather than arbitrary n-gons.

**What it found:** Avoids the ear-clipping n-gon decomposition artifacts that the cluster-collapse approach produced. Merged as the default strategy in `field-aligned-merge-experiments`.

---

### `field-aligned-merge-experiments` — Dome/saddle caps *(LATEST, now on main)*

**Status:** This is the current production code. Merged into `main`.

**What it added over `clean-generalized-pipeline`:**
- `dome_caps.py` — curvature-aware quad-dome/saddle boundary-loop capping for non-planar loops (extends `caps.py` which only handled flat boundaries). Uses SVD-based curvature sign classification (dome vs. saddle), builds concentric quad rings inward with rollback guard if aspect-ratio or minimum-size checks fail.
- `coplanar_merge.py` updated to pairwise non-disk strategy (from `nondisk-planar-merge`)
- Fixed n-gon decomposition collision bug: the `decompose` ear-clipping step was creating faces that collided with existing boundary edges

**Pipeline sequence (finalize_component.py):**
```
darts → coplanar_merge → caps/dome_caps → collinear_cleanup → fix_winding → reproject
```

Note: `dissolve.py` was removed from the finalize sequence in this branch — its full-line tracing is subsumed by the more general `coplanar_merge.py`.

---

### `structured-coplanar-quad-strip` — Quad-strip engine *(experiment)*

**Status:** Experiment. Not merged. Promising approach documented here for future work.

**What it tried:** Instead of coplanar flood-fill merge, operate strictly along **continuous quad strips** (coordinate ribbons). Step across opposite edges (`e_i → e_{i+2}`) and only decimate **complete transverse chords** (spanning boundary-to-boundary or closed rings). Rail vertices dissolve cleanly at valence 2, guaranteeing 100% quads and zero n-gons.

**Tradeoff vs. current approach:** Mathematically cleaner (no n-gons at any point), but requires a dense, well-structured quad mesh from the remesher. On meshes where Instant Meshes falls back to quadric decimation (which produces tris/quads mixed), there are no continuous quad strips to trace.

**Key file:** `core/quad_strip_engine.py` and `QUAD_STRIP_PIPELINE_ARCHITECTURE.md` on this branch.

---

### `percentage-budget` — Percentage face budget *(experiment)*

**Status:** Experiment. Not merged.

**What it tried:** Instead of "minimum faces without feature loss", target a specific face-count band (0.05%–1% of input face count) to match Tripo's reference output density more precisely. Used Catmull-Clark smooth subdivision to fill in detail where the remesher over-decimated.

**What it found:** The budget-driven approach conflicts with the adaptive sizing philosophy: flat surfaces should have very few faces (regardless of percentage), and curved surfaces should have as many as the curvature demands. A fixed percentage forces either too many faces on flat areas or too few on curved ones. Documented in `PROGRESS.md` on this branch.

---

## Which branch to use

For production use, check out `main` — it has the full, clean, documented code from `field-aligned-merge-experiments`.

```bash
git checkout main
python3 run_pipeline.py <input.glb> <output_dir>
```
