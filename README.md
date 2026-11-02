# vacuum_quad_engine (percentage-budget branch)

A curvature-adaptive, quad-dominant retopology pipeline for turning dense
AI-generated (or any dense raw-scan) meshes into clean, Tripo-style
quad-dominant assets. This branch adds an **optional hard output-face-
count band**: the final output is guaranteed to land within
`[min_frac, max_frac] * input_faces` (e.g. 0.5%-3%), with the pipeline's
normal curvature-adaptive, zero-feature-loss sizing still driving
everything when no band is requested.

See [`TECH_NOTES.md`](TECH_NOTES.md) for the full technical log and
[`PROGRESS.md`](PROGRESS.md) for the task-by-task build history,
including the dedicated "Optional hard output-face-count band" section
documenting this branch's feature.

## Pipeline stages (`core/`)

1. **`decompose.py`** — split the input mesh into connected components.
2. **`curvature.py`** — per-vertex curvature field (libigl).
3. **`sizing.py`** — per-component target-face-count hint via
   `h(v) = clip(sqrt(epsilon / kappa(v)), h_min, h_max)`; optionally
   banded into `[min_budget_frac, max_budget_frac] * total_input_faces`
   as a soft pre-remesh shaping hint.
4. **`remesh.py`** — field-aligned quad remeshing (Instant Meshes /
   quadriflow), with a quadric-decimation fallback.
5. **`dissolve.py` / `darts.py` / `coplanar_merge.py`** — redundant-loop
   dissolution and coplanar region merging.
6. **`caps.py`** — parallel-chord quad caps for planar boundaries.
7. **`fix_winding.py`** — BMesh-native winding-consistency repair.
8. **`reproject.py`** — CAD-surface reprojection onto the original dense
   input.
9. **`subdivide_mesh.py`** — quad-preserving bmesh subdivision, used only
   by the hard output-band enforcement below to raise face count to a
   user-mandated floor.
10. **`audit.py`** — forensic topology metrics.
11. **`pipeline.py`** — orchestrates all of the above, including the
    optional post-join hard output-face-band enforcement
    (`_enforce_output_face_band`): subdivides up (quad-preserving) or
    quadric-decimates down (triangulating) as needed to guarantee the
    final count lands in the requested band.

## Usage

```bash
# Normal, unconstrained (curvature-adaptive minimum, no budget):
python3 core/pipeline.py <input.glb|.fbx|.obj> <out_dir>

# Hard-guaranteed output band, e.g. 0.5%-3% of input faces:
python3 core/pipeline.py <input.glb|.fbx|.obj> <out_dir> 0.005 0.03
```

Requires Blender (for `bpy`/`bmesh`) and system Python 3 with `trimesh`
and `libigl` for curvature/decimation. See `core/config.py` for binary
path resolution.
