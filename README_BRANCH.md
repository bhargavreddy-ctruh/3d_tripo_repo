# Branch: `no-blender-pure-python` — Milestone: Eliminate Blender

**Status:** Milestone — superseded by `clean-generalized-pipeline`. Use that branch or `main` for production.

## What This Branch Achieved

This is the branch where Blender (`bpy`, `bmesh`, the `blender` binary) was eliminated entirely from the pipeline. Every stage now runs as a plain Python function call in a single process — no subprocess, no IPC, no version pinning.

### Key changes

| Old (Blender-based) | New (pure Python) |
|---------------------|-------------------|
| `core/io_blender.py` (bpy import/export) | `core/io_mesh.py` (trimesh + OBJ) |
| `bmesh.ops.*` for editing | `core/editmesh.py` — mutable polygon mesh |
| `blender --python` subprocess per stage | Direct function call, same process |

**`core/editmesh.py`** is the central data structure: a mutable vertex/edge/face mesh with adjacency that preserves face arity (quads and n-gons stay as quads and n-gons — unlike `trimesh.Trimesh` which is triangle-only). It replaces `bmesh` as the shared structure threaded through `dissolve.py`, `darts.py`, `coplanar_merge.py`, `caps.py`, `fix_winding.py`.

### Three bugs fixed on this branch

1. **Broken fragmentation check** — was always reporting "no fragments" regardless of actual component count
2. **Phantom islands** — the decomposer was counting disconnected sub-meshes that didn't exist
3. **Bad coplanar merges** — merge_faces winding was computed at the wrong point (after, not before, the merge), producing flipped normals on flat surfaces

## Pipeline on This Branch

```
input.glb/obj
  → decompose.py     (connected components)
  → sizing.py        (curvature-based target-face hint)
  → remesh.py        (Instant Meshes / quadriflow / quadric decimation)
  → dissolve.py      (transverse-loop dissolution on EditMesh)
  → darts.py         (coplanar triangle-pair merge)
  → caps.py          (planar boundary loop capping)
  → fix_winding.py   (BFS winding repair)
  → reproject.py     (snap to original dense surface)
  → audit.py         (topology metrics)
```

## Running

```bash
python3 run_pipeline.py <input.glb|.obj> <output_dir>
```

Dependencies: `numpy`, `trimesh`. Optional: `libigl` for curvature stage.

## Key Commits

- `4bf782d` — Eliminate Blender entirely: pure-Python mesh pipeline
- `0b1fb46` — Fix merge_faces winding at the source
- `ec927c0` — Fix three quality bugs: fragmentation, phantom islands, bad merges

## Next Branch

→ [`clean-generalized-pipeline`](https://github.com/bhargavreddy-ctruh/3d_tripo_repo/tree/clean-generalized-pipeline) — adds structured coplanar merge (`coplanar_merge.py`) that handles valence ≠ 4 vertices (the main limitation of `dissolve.py` on this branch).
