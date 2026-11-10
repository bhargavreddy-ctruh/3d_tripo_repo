# Branch: `percentage-budget` — Experiment: 0.05%–1% Face Count Budget

**Status:** Experiment — not merged. Findings documented here.

## What This Branch Tried

Instead of "minimum faces without feature loss" (the approach on `main`), target a specific face-count band: **0.05%–1% of the input face count**. This was motivated by comparing against real Tripo exports, which tend to land in that density range.

### Implementation

1. After remeshing to the curvature-adaptive target, check if the output face count lands outside the 0.05%–1% band.
2. If too dense: re-run with a more aggressive quadric decimation.
3. If too sparse (which never happens in practice): subdivide using Catmull-Clark smooth subdivision (not linear cuts, to avoid introducing new diagonal slashes).

A `--percentage` flag was added to `run_pipeline.py` to enable this mode.

### What It Found

The percentage-budget approach conflicts with the adaptive sizing philosophy:

- **Flat surfaces** (a sofa seat, a wooden panel) should have very few faces regardless of their area — the percentage of a large flat mesh is too many faces.
- **Curved surfaces** (a koala's head, a dragon's claw) need as many faces as the curvature demands — the percentage of a small curved detail is too few.

A fixed percentage forces either too many faces on flat areas or too few on curved ones. The result is a uniform-density retopology that doesn't respect the mesh's actual information content.

**Final finding:** Tripo's reference density range is a consequence of their pipeline's adaptive sizing decisions, not a constraint to target directly. Attempting to match that range as a hard constraint degrades topological quality.

### Benchmark files

This branch has the most comprehensive benchmark set (`benchmarks/`) with real measurements against 9 reference Tripo exports. These benchmarks confirmed the face-count targets were met within the 0.05%–1% band, but at the cost of topology quality on flat surfaces.

## Key Commits

- `375a740` — Fix blocky subdivision: use Catmull-Clark smooth subsurf, not linear cuts
- `fadee63` — Fix the real problem: floor-aware finalize instead of post-hoc density
- `5bda34d` — Document verified results for the tighter 0.05%-1% output band

## Next Step

The benchmarks (`benchmarks/*.json`) are worth porting to `main` as quality reference data, even though the percentage-budget approach itself was abandoned.
