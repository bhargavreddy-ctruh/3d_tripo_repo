# Branch: `nondisk-planar-merge` — Experiment: Multi-Hole Coplanar Merge

**Status:** Experiment — merged into `field-aligned-merge-experiments`. Not the production branch.

## What This Branch Tried

Extended `coplanar_merge.py` to correctly handle coplanar regions with **holes** (non-disk topology) — for example, a flat surface with one or more circular cutouts.

### The problem with single-cluster collapse on non-disk regions

The original `coplanar_merge.py` collapsed an entire coplanar cluster into one face using `mesh.merge_faces(cluster)`. When the cluster has holes, this produces a single large n-gon with an undefined interior — the boundary of the face traces the outer perimeter and all hole perimeters, creating a face that cannot be represented as a simple polygon. The subsequent n-gon decomposition (`resolve_all_ngons`) then uses 2D ear-clipping, which produces arbitrary diagonal slashes across the interior, destroying all quad flow.

### The pairwise non-disk solution

Instead of collapsing the whole cluster at once, merge **adjacent face pairs** iteratively. Each merge step produces only 4-to-6-gon intermediates (two faces sharing one edge → one face), never an arbitrary n-gon. The result is a sequence of small, clean merges that naturally routes around hole boundaries without needing an ear-clipper.

**Key invariant:** No intermediate face ever has more vertices than the number of vertices on its own boundary. The merge is always topologically safe.

## Key Commit

- `b0098b7` — feat(coplanar_merge): pairwise non-disk coplanar merge for multi-holed surfaces

## Next Branch

→ [`field-aligned-merge-experiments`](https://github.com/bhargavreddy-ctruh/3d_tripo_repo/tree/field-aligned-merge-experiments) — adopts the pairwise approach as the default strategy and adds dome/saddle caps.
