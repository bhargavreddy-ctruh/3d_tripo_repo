# no_blender_pipeline — Pure-Python Quad-Dominant Retopology

A pure-Python, zero-Blender pipeline that converts dense raw scans and AI-generated meshes
(GLB/GLTF/OBJ) into clean, quad-dominant retopologized assets: large flat n-gon panels,
clean quad bevels/legs, and minimal triangles.

**Zero Blender dependency** — no desktop application, no `bpy` module, no subprocess
spawning into a DCC tool. Every mesh-editing stage runs in-process on a custom mutable
polygon mesh (`core/editmesh.py`). The only external binary is a field-aligned remesher
(Instant Meshes, bundled in `bin/`).

---

## Quick Start

```bash
# 1. Install pinned Python dependencies
pip install -r requirements.txt

# 2. Run the pipeline on any asset
python3 run_pipeline.py assets/inputs/woodenrack_854k.glb outputs/pipeline
```

That's it — `bin/instant_meshes` and `assets/inputs/*.glb` are committed to this repo, so
a fresh `git clone` + `pip install` + the command above reproduces the exact output below
with no machine-specific setup.

### CLI usage

```
python3 run_pipeline.py <input_mesh.(obj|glb|gltf)> <output_directory> [max_dissolve_passes]
```

- `input_mesh` — path to a `.glb`, `.gltf`, or `.obj` file.
- `output_directory` — required; all stage output goes here (see below).
- `max_dissolve_passes` — optional, default `20`.

### What gets written to `<output_directory>/`

For an input named `<base_name>.glb`:

- `<base_name>__final.obj` — the deliverable mesh (quads/n-gons preserved, not triangulated).
- `<base_name>__report.json` — per-stage timings, component count, remesh backend used, and
  the full topology audit (face/quad/tri/ngon counts, non-manifold edges, aspect ratios).
- `<base_name>__components/`, `<base_name>__remeshed/`, `<base_name>__finalized/` —
  intermediate per-stage working directories. These are **not** auto-deleted; safe to
  `rm -rf` between runs if you only want the final files.

There is no GLB export and no wireframe PNG produced automatically. To render a QA
wireframe (yellow = n-gon, blue = quad, red = tri) from any `.obj`:

```bash
python3 core/render_honest_wireframe.py <path>__final.obj <path>__wireframe.png --title "<name>"
```

---

## Verified Reference Results

Run on 2026-11-11 against this exact commit, `assets/inputs/*.glb` → `outputs/pipeline/`:

| Asset | Final Faces | Quads | Tris | N-gons | Non-Manifold |
| :--- | ---: | ---: | ---: | ---: | :---: |
| `000.glb` | 11,954 | 5,902 | 552 | 5,500 | 0 |
| `002.glb` | 8,586 | 4,366 | 488 | 3,732 | 0 |
| `koala_1790k.glb` | 6,631 | 2,370 | 148 | 4,113 | 0 |
| `sofa_860k.glb` | 579 | 253 | 31 | 295 | 0 |
| `woodenrack_854k.glb` | 352 | 202 | 34 | 116 | 0 |

If a run on this exact commit produces different numbers, something in the environment
(Instant Meshes binary, dependency versions, or an uncommitted local edit) has drifted —
diff against `core/config.py` and the pinned versions in `requirements.txt` first.

---

## Dependencies

Pinned in `requirements.txt` (versions verified against the table above):

```
numpy==2.5.1
scipy==1.18.0
trimesh==5.0.0
libigl==2.6.3
matplotlib==3.11.1
```

`core/config.py` auto-detects the remesher binary at `bin/instant_meshes` (committed in
this repo, macOS x86_64). To sanity-check binary + dependency resolution on a new machine:

```bash
python3 core/config.py
```

should print a resolved `INSTANT_MESHES_BIN` path and `Environment OK.`.

---

## Architecture & Documentation

- **[PIPELINE_ARCHITECTURE.md](PIPELINE_ARCHITECTURE.md)** — stage-by-stage architecture and
  data flow.
- **[BRANCHES.md](BRANCHES.md)** — branch lineage guide for this repository's experiments.
- **`core/config.py`** — binary paths and all angle/sizing tunables.
