# Branch: `clean-generalized-pipeline` — Milestone: Structured Planar Merge

**Status:** Milestone — superseded by `field-aligned-merge-experiments` (adds dome/saddle caps). Use `main` for production.

## What This Branch Added

Introduced `core/coplanar_merge.py` — a general coplanar-region flood-fill merge that eliminates all interior diagonal chords and redundant edges across flat surfaces, without being limited to valence-4 vertices.

### Why `dissolve.py` wasn't enough

`dissolve.py`'s transverse-loop tracer walks along the quad ribbon via opposite edges (`e → e+2`). At each step it must cross a valence-4 vertex. But measurement on real Instant Meshes output shows valence-3 is nearly as common as valence-4 on curved surfaces — the tracer stalls at ~40% of interior vertices, leaving most redundant edges untouched.

`coplanar_merge.py` replaces the loop paradigm with a flood-fill: cluster all faces that share the same surface normal (within a threshold), then merge each cluster into a single face. This handles all valence values and eliminates interior edges that the loop tracer can't reach.

### Pipeline on this branch

```
input → decompose → sizing → remesh
      → darts (tri-pair merge)
      → coplanar_merge (planar flood-fill)
      → caps (planar boundary loops)
      → fix_winding
      → reproject
      → audit
```

Note: `dissolve.py` is still present but no longer the primary simplification stage — `coplanar_merge.py` subsumes it for flat surfaces.

## Running

```bash
python3 run_pipeline.py <input.glb|.obj> <output_dir>
```

## Key Commits

- `2505047` — feat(pipeline): latest generalized retopology pipeline with minimal faces, structured planar merging, clean topology
- `4972de0` — fix(retopo): strict full-line pairwise quad decimation

## Next Branch

→ [`field-aligned-merge-experiments`](https://github.com/bhargavreddy-ctruh/3d_tripo_repo/tree/field-aligned-merge-experiments) — adds dome/saddle boundary-loop capping for non-planar boundaries and pairwise non-disk coplanar merge.
