# no_blender_pipeline — Quad-Dominant Retopology Pipeline

A pure-Python, Blender-free pipeline that converts dense AI-generated or raw-scan meshes (GLB/GLTF/OBJ) into clean quad-dominant assets suitable for Tripo and similar production pipelines.

**No Blender dependency** — not the desktop app, not the `bpy` pip module, not even as a subprocess. Every mesh operation runs in-process on a custom mutable polygon-mesh structure (`core/editmesh.py`).

---

## Quick Start

```bash
pip install numpy trimesh
python3 run_pipeline.py <input.glb|.obj> <output_dir>
```

The optional third argument caps the number of merge passes (default: 20):

```bash
python3 run_pipeline.py assets/inputs/sofa_860k.glb outputs/sofa 10
```

Output files written to `<output_dir>/`:
- `<name>__final.obj` — retopologised mesh (the deliverable)
- `<name>__report.json` — timing, component count, and topology audit metrics
- `<name>__components/` — per-component decomposition OBJs (intermediate)
- `<name>__remeshed/` — per-component Instant Meshes / quadriflow output (intermediate)
- `<name>__finalized/` — per-component finished OBJs before join (intermediate)

### Render a wireframe for QA

```bash
python3 core/render_honest_wireframe.py <output>__final.obj wireframe.png \
    --title "my mesh (Nk → M faces)" --elev 25 --azim -60
```

> Uses direct OBJ face parsing — never `trimesh.load(force='mesh')` — so quads and n-gons render as genuine polygons instead of forced triangles.

---

## Pipeline Stages (`core/`)

| Stage | Module | What it does |
|-------|--------|--------------|
| 1 | `decompose.py` | Splits input into connected components (never merged into one, fixing global-target bugs in naive pipelines) |
| 2 | `curvature.py` | Per-vertex curvature field (libigl) — single source of truth for sizing and edge protection |
| 3 | `sizing.py` | Per-component target-face hint: `h(v) = clip(√(ε/κ(v)), h_min, h_max)` |
| 4 | `remesh.py` | Field-aligned quad remesh via Instant Meshes (preferred) with quadriflow fallback, then quadric-decimation fallback |
| 5 | `darts.py` | Coplanar triangle-pair merge (diamond-dart adapters) — collapses tri+tri pairs into quads before loop traversal |
| 6 | `coplanar_merge.py` | General coplanar-region merge — eliminates all interior diagonal chords and redundant edges across flat surfaces |
| 7 | `caps.py` + `dome_caps.py` | Quad caps for planar and curved boundary loops — eliminates triangle-fan pole singularities |
| 8 | `fix_winding.py` | BFS winding-consistency repair that preserves quad/n-gon arity |
| 9 | `reproject.py` | Snaps simplified mesh back onto original dense surface via nearest-surface-point projection |
| 10 | `audit.py` | Topology metrics: quad%, tri%, n-gon%, valence-4%, aspect ratios, boundary edges |
| — | `pipeline.py` | Orchestrates all of the above end to end |

### Supporting modules

| Module | Purpose |
|--------|---------|
| `editmesh.py` | Mutable polygon mesh (verts/edges/faces + adjacency) — replaces `bmesh`; preserves face arity unlike `trimesh.Trimesh` |
| `obj_io.py` | Minimal OBJ reader/writer that preserves native face arity (quad/n-gon/tri) |
| `io_mesh.py` | OBJ/GLB/GLTF I/O layer |
| `protect.py` | Curvature-weighted edge protection/cost field for dissolution |
| `config.py` | Binary paths and tunable thresholds |
| `render_honest_wireframe.py` | QA wireframe renderer (direct OBJ parse, no forced triangulation) |
| `render_protect_debug.py` | Visualise protect.py's edge-cost field |

---

## Supported Formats

| Format | Input | Output |
|--------|-------|--------|
| OBJ | ✅ | ✅ |
| GLB / GLTF | ✅ | — (output is always OBJ) |
| FBX | ❌ | ❌ |

Pre-convert FBX assets to GLB or OBJ before running the pipeline.

---

## Dependencies

```bash
pip install numpy trimesh
# For curvature stage (optional but recommended):
pip install libigl
```

The external `bin/instant_meshes` binary is required for field-aligned remeshing. If it's absent or fails, the pipeline falls back to quadriflow (if installed) and then to trimesh quadric decimation automatically.

---

## Example Results

| Mesh | Input faces | Output faces | Quad % | Time |
|------|-------------|-------------|--------|------|
| sofa_860k.glb | 860,218 tri | 754 | 42% | ~40 s |
| woodenrack_854k.glb | 854,832 tri | 365 | 59% | ~54 s |

Wireframe renders are in [`outputs/examples/`](outputs/examples/).

---

## Branch History

See [`BRANCHES.md`](BRANCHES.md) for a summary of every development branch, what each one experimented with, and which is the current production branch.

---

## Architecture Decision: Why Not Blender?

The original pipeline (`vacuum_quad_engine` on the first `main` commit) used Blender's `bpy` Python module for mesh I/O and all editing operations. This caused:

- Version-pinning hell (the `bpy` pip wheel must exactly match the installed Blender version)
- Multi-second process start-up overhead per pipeline stage
- No ability to share mesh state in-process between stages

`core/editmesh.py` replaces `bmesh` with a plain mutable polygon-mesh that lives in a single Python process for the full pipeline run. `core/io_mesh.py` replaces `io_blender.py` for OBJ/GLB/GLTF loading.
