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
7. **`fix_winding.py`** — BMesh-native, quad/n-gon-preserving winding-
   consistency repair.
8. **`reproject.py`** — CAD-surface reprojection back onto the original
   dense input.
9. **`audit.py`** — forensic topology metrics (quad%, valence-4%, boundary
   edges, aspect ratios) for comparing output against real Tripo exports.
10. **`pipeline.py`** — orchestrates all of the above end to end.

## Usage

```bash
python3 core/pipeline.py <input.glb|.fbx|.obj> <out_dir>
```

Requires the `bpy` pip package (Blender as an in-process Python module —
`pip install bpy`) plus `trimesh`/`numpy`/`libigl` for curvature/decimation,
all in the same interpreter that runs `pipeline.py`. `bpy` wheels are only
published for specific CPython versions (check
https://pypi.org/project/bpy/#files for the current one — e.g. `bpy==5.2.3`
needs Python 3.13), so this will likely need its own venv separate from
whatever Python the rest of the project uses:

```bash
python3.13 -m venv .venv-bpy
.venv-bpy/bin/pip install bpy==5.2.3 trimesh numpy libigl
.venv-bpy/bin/python core/pipeline.py <input.glb|.fbx|.obj> <out_dir>
```

Pick the `bpy` version that matches the installed Blender.app's version
(`core/config.py`'s `BLENDER_BIN` prints it) so operators/importers behave
identically to the desktop app. Previously this pipeline shelled out to a
separate `blender --background --python ...` subprocess per stage (13+
full Blender startups for a 10-component asset); it now runs entirely
in-process — Blender starts once per `pipeline.py` run and is reused for
every decompose/finalize/join/audit call. A standalone desktop Blender.app
install is no longer required to run the pipeline, only to cross-check
`bpy`'s version against (see `core/config.py`).
