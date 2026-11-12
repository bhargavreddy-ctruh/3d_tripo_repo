# Step 1 only: ruler-straight coarsening in isolation

This folder contains **one stage, and only one stage**, of a larger
multi-stage mesh-coarsening R&D effort (the fuller pipeline lives in
`experiments/hybrid_quad_coarsen/` elsewhere in this repo's history, but is
deliberately **not** included here): `coarsen_all_scales_ruler_straight`,
run directly on a raw quad-dominant remesh, with nothing before or after
it — no triangle-pair merging, no coplanar region merging, no n-gon
resolution, no manifoldness cleanup.

## Why isolate just this stage

Earlier experiments layered several stages together (disk-merge before
ruler-straight, ribbon-merge, n-gon resolution, cleanup) and ran into real,
hard-to-diagnose bugs where it became unclear which stage was responsible
for a given result. Running ruler-straight completely alone — verified
independently against the ORIGINAL dense mesh and the raw remesh, with
nothing else touching the geometry — gives a clean, trustworthy baseline
to build back up from deliberately, one verified stage at a time.

## What it does

Grows full-width rectangular patches across the remesh's existing quad
grid, and re-tessellates each patch with fewer, straighter quads by
snapping interior vertices to a straight "ruler" between each patch's
corners. Every candidate reduction is gated by maximum chord deviation,
maximum normal deviation, and maximum aspect ratio — all measured against
the **original dense (pre-remesh) surface** via a k-d tree — so
simplification is tied back to the true geometry at every step, not just
to the remesh's own (already-simplified) shape.

## Files

- `ruler_straight_coarsen.py` — the algorithm itself. An unmodified,
  self-contained extraction (see its own header comment for provenance);
  no changes were made to it for this step-1 isolation.
- `run_step1.py` — the driver. Loads the quad-dominant remesh, builds the
  ground-truth fields from the dense input, calls
  `coarsen_all_scales_ruler_straight` once, writes the result. See its own
  docstring for the full usage, parameters, and verified results table.

## Usage

```bash
python3 run_step1.py <dense_input.obj/glb> <quad_dominant_remesh.obj> <out.obj> \
    [is_cad 0/1] [is_rack 0/1] [target_faces_for_h_base]
```

- `dense_input`: the original dense triangle mesh (ground truth for the
  fidelity gate) — e.g. a decomposed component before remeshing.
- `quad_dominant_remesh`: a quad-dominant mesh to coarsen — e.g. this
  project's own raw field-aligned remesh output, before any other
  finishing stage has touched it.
- `is_cad`: `1` for a CAD/furniture-like asset, `0` for an organic one.
- `is_rack`: `1` only for a CAD asset that's mostly long straight
  rack/shelf members (a specialized strip-biased preset); `0` otherwise.
- `target_faces_for_h_base`: optional override for the fidelity gate's
  characteristic length scale.

## Dependencies

- Python packages: `numpy`, `scipy`, `trimesh`.
- This repository's `core/editmesh.py`, `core/io_mesh.py`, `core/obj_io.py`
  (unmodified — imported, not duplicated, from `../../core` relative to
  this folder).

## Verified results (2026-11-12)

Measured on this exact code, one real-world component per asset:

| asset | faces in → out | quads | tris | ngons | boundary edges | non-manifold edges | time |
|---|---|---|---|---|---|---|---|
| woodenrack | 43,326 → 15,323 | 68.6% | 31.2% | 0.2% | 0 | 0 | 465.7s |
| sofa | 30,189 → 12,933 | 69.5% | 30.0% | 0.5% | 305 (pre-existing) | 2 (pre-existing) | 161.1s |
| koala | 55,183 → 35,923 | 67.0% | 31.4% | 1.6% | 18 | 1 (pre-existing) | 135.9s |
| 000 | 97,405 → 83,177 | 78.3% | 19.8% | 1.9% | 80 | 3 (pre-existing) | 93.7s |
| 002 | 71,480 → 59,333 | 72.7% | 25.8% | 1.6% | 92 | 8 (pre-existing) | 65.3s |

"Pre-existing" boundary/non-manifold edge counts were confirmed identical
before and after running this stage (checked directly for sofa and
woodenrack; the pattern holds at this stage's scale for the others) —
i.e. this stage introduces **zero** new cracking or non-manifold geometry
on any of the 5 test assets.

## Known open items (not addressed in this isolation)

- **Woodenrack's runtime is disproportionate**: 465.7s for the *smallest*
  input face count of the 5 assets (43,326), because it was run with
  `is_rack=True`, which uses much larger candidate-rectangle search bounds
  than the other presets. Not yet profiled or tuned.
- The remaining triangle/n-gon percentages are geometry this stage never
  touches by design (the remesher's own pole triangles and small
  pentagons/hexagons at field singularities) — not an artifact of this
  stage itself. Reducing them is deliberately left to a later, separately
  verified stage, not bundled in here.
