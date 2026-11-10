# Branch: `proper-quads-full-lines` — Experiment: Strict Full-Line Quad Decimation

**Status:** Experiment — findings merged into `clean-generalized-pipeline`. Not the production branch.

## What This Branch Tried

Enforce that `dissolve.py`'s loop dissolution only collapses a **complete edge loop** from boundary to boundary (or a complete closed ring), never an isolated interior edge. This prevents T-junctions — the main artifact where a partial loop dissolution leaves a valence-3 vertex that then forces a diagonal slash through the adjacent face during triangulation.

## What It Found

The strict full-line rule works well on **flat or low-curvature regions** where quad loops run cleanly parallel. On **curved organic surfaces**, the full-line tracer terminates prematurely: the traversal requires passing through valence-4 vertices, but valence-3 is nearly as common as valence-4 on real Instant Meshes output (confirmed by measurement). The result is a large number of short, non-terminating loop fragments — most interior edges are left untouched.

**Root cause:** `dissolve.py`'s transverse-loop tracer has an implicit `valence == 4` guard at every step. On a typical remesher output, ~40% of interior vertices are valence-3, breaking the loop continuity at almost every turn on curved surfaces.

**Fix (implemented in `clean-generalized-pipeline`):** Replace transverse-loop tracing with a flood-fill coplanar-region merge (`coplanar_merge.py`) that handles all valence values.

## Key Commit

- `4972de0` — fix(retopo): strict full-line pairwise quad decimation & seam-to-seam ribbon merge

## Next Branch

→ [`clean-generalized-pipeline`](https://github.com/bhargavreddy-ctruh/3d_tripo_repo/tree/clean-generalized-pipeline) — replaces the loop tracer with a valence-agnostic coplanar flood-fill merge.
