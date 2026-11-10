# vacuum_quad_engine — Quad-Dominant Retopology Pipeline

> **This is the original Blender-based baseline.** The production pipeline is on the `field-aligned-merge-experiments` branch (now also the definitive version of `main`). See [`BRANCHES.md`](BRANCHES.md) for the full development history.

---

A curvature-adaptive, quad-dominant retopology pipeline for turning dense AI-generated (or any dense raw-scan) meshes into clean, Tripo-style quad-dominant assets.

## Production branch

The current production code is **`field-aligned-merge-experiments`** (pure Python, no Blender required):

```bash
git checkout field-aligned-merge-experiments
pip install numpy trimesh
python3 run_pipeline.py <input.glb|.obj> <output_dir>
```

See that branch's [`README.md`](https://github.com/bhargavreddy-ctruh/3d_tripo_repo/blob/field-aligned-merge-experiments/README.md) for full documentation.

## This branch (original)

This branch (`main`) contains the original `vacuum_quad_engine` — a Blender-dependent pipeline. It requires Blender to be installed and the `bpy` pip wheel to match the installed Blender version.

**Do not use this branch for production.** It is kept for historical reference only.

### Original pipeline stages (`core/`)

1. **`decompose.py`** — split the input mesh into connected components
2. **`curvature.py`** — per-vertex curvature field (libigl)
3. **`sizing.py`** — per-component face count hint via `h(v) = clip(√(ε/κ(v)), h_min, h_max)`
4. **`remesh.py`** — Instant Meshes / quadriflow field-aligned remeshing
5. **`dissolve.py` / `darts.py` / `coplanar_merge.py`** — redundant-loop dissolution and coplanar merging
6. **`caps.py`** — boundary loop capping
7. **`fix_winding.py`** — winding repair
8. **`reproject.py`** — reprojection onto original dense surface
9. **`audit.py`** — topology metrics
10. **`pipeline.py`** — orchestrates stages via `bpy` / `io_blender.py`

### Original usage (requires Blender)

```bash
python3 core/pipeline.py <input.glb|.obj> <out_dir>
```

---

## Development history

See [`BRANCHES.md`](BRANCHES.md) and [`TECH_NOTES.md`](TECH_NOTES.md) for the full technical log of every decision made across the development branches.
