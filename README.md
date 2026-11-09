# vacuum_quad_engine

A curvature-adaptive, quad-dominant retopology pipeline for turning dense
AI-generated (or any dense raw-scan) meshes into clean, Tripo-style
quad-dominant assets: dense faces where curvature/detail genuinely exists,
large clean flat faces where it doesn't, with **no fixed face-count
budget** — minimum faces subject to zero feature loss.

See [`TECH_NOTES.md`](TECH_NOTES.md) for the full technical log (every
tool/library/threshold decision, every bug found and fixed, with evidence)
and [`PROGRESS.md`](PROGRESS.md) for the task-by-task build history.

## Pipeline stages (`core/`)

1. **`decompose.py`** — split the input mesh into connected components
   (never joined into one, unlike most naive retopology pipelines).
2. **`curvature.py`** — per-vertex curvature field (libigl), the single
   source of truth driving both sizing and protection downstream.
3. **`sizing.py`** — per-component target-face-count hint via
   `h(v) = clip(sqrt(epsilon / kappa(v)), h_min, h_max)`, integrated over
   each component's own area.
4. **`remesh.py`** — field-aligned quad remeshing (Instant Meshes /
   quadriflow), with a quadric-decimation fallback when both fail.
5. **`dissolve.py` / `darts.py` / `coplanar_merge.py`** — redundant-loop
   dissolution, coplanar triangle-pair merging, and general coplanar
   flood-fill region merging.
6. **`caps.py`** — parallel-chord quad caps for planar circular/polygonal
   boundaries (eliminates triangle-fan pole singularities).
7. **`fix_winding.py`** — quad/n-gon-preserving winding-consistency repair.
8. **`reproject.py`** — CAD-surface reprojection back onto the original
   dense input.
9. **`audit.py`** — forensic topology metrics (quad%, valence-4%, boundary
   edges, aspect ratios) for comparing output against real Tripo exports.
10. **`pipeline.py`** — orchestrates all of the above end to end.

## Usage

```bash
python3 core/pipeline.py <input.glb|.obj> <out_dir>
```

**No Blender dependency at all** — not the desktop app, not the `bpy` pip
module, not even as a subprocess. Every mesh operation (import/export,
dissolve, triangle-pair merging, coplanar-region merging, boundary
capping, winding repair, reprojection) is implemented directly on
`core/editmesh.py`'s own mutable polygon-mesh structure (numpy-based,
preserves quads/n-gons — unlike `trimesh.Trimesh`, which is triangle-only)
plus `trimesh`/`libigl` for curvature, remeshing's external binaries, and
decimation. See `core/io_mesh.py` for the OBJ/GLB/GLTF I/O layer and
`core/config.py` for remesher binary path resolution.

Only `.obj`/`.glb`/`.gltf` inputs are supported — **FBX is not supported
by this pipeline**. There is no pure-Python FBX reader/writer wired up
(trimesh can't reliably parse FBX either); pre-convert `.fbx` assets to
`.obj`/`.glb` before running the pipeline.

Dependencies: `numpy`, `trimesh`, `igl` (`python3 -m pip install numpy
trimesh libigl`). No GPU, no Blender install, no matching-version pip
wheel to track.
