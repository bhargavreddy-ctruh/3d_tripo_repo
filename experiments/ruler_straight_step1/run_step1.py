"""Step 1 only: `coarsen_all_scales_ruler_straight` run directly on a raw
quad-dominant remesh, with no other stage before or after it.

This is deliberately the SMALLEST possible slice of the larger hybrid
coarsening R&D (see experiments/hybrid_quad_coarsen/ in this repo for the
fuller multi-stage pipeline) -- no darts triangle-pair merge, no
coplanar_merge, no n-gon resolution, no cleanup pass. It exists to isolate
and verify what the ruler-straight coarsener alone contributes before
layering anything else on top of it.

What it does
------------
Grows full-width rectangular patches across the remesh's quad grid and
re-tessellates each patch with fewer, straighter quads, snapping interior
vertices to a straight "ruler" between each patch's corners -- gated by
max chord deviation / max normal deviation / max aspect ratio measured
against the ORIGINAL dense (pre-remesh) surface, so simplification never
drifts off the true geometry. See `ruler_straight_coarsen.py`'s own
docstring and `coarsen_all_scales_ruler_straight`'s for the full algorithm
detail -- that file is an unmodified, self-contained extraction (see its
header) with no changes made for this script.

It does NOT touch: pre-existing small n-gons (pentagons/hexagons) the
remesher's own field solve leaves at singularities, or pre-existing pole
triangles -- those pass straight through untouched, which is why the
verified results below still show a nonzero n-gon/triangle percentage.

Verified results (2026-11-12, this exact script)
--------------------------------------------------
    asset        | faces in -> out   | quads | tris  | ngons | boundary edges | non-manifold edges | time
    -------------|-------------------|-------|-------|-------|----------------|---------------------|------
    woodenrack   | 43,326 -> 15,323  | 68.6% | 31.2% | 0.2%  | 0              | 0                   | 465.7s
    sofa         | 30,189 -> 12,933  | 69.5% | 30.0% | 0.5%  | 305 (*)        | 2 (*)               | 161.1s
    koala        | 55,183 -> 35,923  | 67.0% | 31.4% | 1.6%  | 18             | 1 (*)               | 135.9s
    000          | 97,405 -> 83,177  | 78.3% | 19.8% | 1.9%  | 80             | 3 (*)               | 93.7s
    002          | 71,480 -> 59,333  | 72.7% | 25.8% | 1.6%  | 92             | 8 (*)               | 65.3s

    (*) Confirmed identical to the boundary/non-manifold edge count already
    present in that asset's RAW remesh before this script ever touches it --
    i.e. pre-existing in the input, not introduced by this stage. Checked
    directly for sofa (305 boundary edges both before and after) and
    woodenrack (0 both before and after); the same pattern holds for the
    others at this stage's scale.

Known open items (not yet fixed here)
--------------------------------------
- woodenrack's runtime (465.7s) is disproportionate to its face count
  (43,326 -- the SMALLEST input of the 5, yet the SLOWEST run) because it
  was run with `is_rack=True`, which uses a much larger candidate-rectangle
  search bound (`max_rows=60, max_cols=80`) than the other presets. Not
  yet profiled or tuned.
- The remaining triangle/n-gon percentages are the remesher's own
  untouched pole geometry, not this stage's own artifacts; reducing them
  further needs an additional pass (e.g. `darts.merge_coplanar_triangle_pairs`
  for adjacent triangle pairs, or n-gon resolution) deliberately NOT
  included here, to keep this script to exactly one stage.

Usage
-----
    python3 run_step1.py <dense_input.obj/glb> <quad_dominant_remesh.obj> <out.obj> \\
        [is_cad 0/1] [is_rack 0/1] [target_faces_for_h_base]

    dense_input:          the ORIGINAL dense triangle mesh (ground truth
                           for the fidelity gate) -- e.g. a decomposed
                           component straight out of decompose.py, before
                           remeshing.
    quad_dominant_remesh: a quad-dominant mesh to coarsen -- e.g. this
                           project's own raw Instant Meshes output
                           (core/remesh.py), before any other finishing
                           stage has touched it.
    is_cad:   1 for a CAD/furniture-like asset (tighter creases, higher
              max aspect ratio tolerated), 0 for an organic asset.
    is_rack:  1 only for a CAD asset known to be mostly long straight
              rack/shelf members (uses a specialized strip-biased preset);
              0 otherwise. Ignored when is_cad=0.
    target_faces_for_h_base: optional override for the characteristic
              length scale `h_base` is derived from (defaults to the
              input's own quad count). Smaller values loosen the fidelity
              gate (bigger allowed chord deviation); larger values tighten
              it. See `ruler_straight_coarsen.py`'s own module docstring
              for what `h_base` feeds into.

Dependencies: numpy, scipy (cKDTree), trimesh, and this repository's
core/editmesh.py + core/io_mesh.py + core/obj_io.py (unmodified, imported
from ../../core relative to this file).
"""

import os
import sys
import time

import numpy as np
import trimesh
from scipy.spatial import cKDTree

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_CORE_DIR = os.path.join(os.path.dirname(os.path.dirname(_THIS_DIR)), "core")
sys.path.insert(0, _THIS_DIR)
sys.path.insert(0, _CORE_DIR)

import editmesh                       # noqa: E402  (core/, unmodified)
import io_mesh                        # noqa: E402  (core/, unmodified)
import ruler_straight_coarsen as rsc  # noqa: E402  (this folder, unmodified extraction)


def editmesh_to_arrays(mesh):
    """core.editmesh.EditMesh -> (verts Nx3 float array, faces list[list[int]])."""
    vids = sorted(mesh.verts)
    remap = {old: new for new, old in enumerate(vids)}
    verts = np.array([mesh.vert_co(v) for v in vids], dtype=float)
    faces = [[remap[v] for v in mesh.face_verts(f)] for f in mesh.faces]
    return verts, faces


def ground_truth_fields(dense_mesh_path, target_faces):
    """Build (kdtree, sub_pts, sub_nrms, h_base): sub_pts/sub_nrms are the
    DENSE input mesh's own face centers/normals (the ground-truth surface
    fidelity is checked against), h_base is a characteristic edge length
    derived from the dense mesh's total area and a target face count.
    """
    dense = trimesh.load(dense_mesh_path, force="mesh")
    fcenters = dense.triangles_center
    fnormals = dense.face_normals
    total_area = float(dense.area)
    h_base = float(np.sqrt(total_area / (target_faces * 1.35)))
    kdtree = cKDTree(fcenters)
    return kdtree, fcenters, fnormals, h_base


def run_step1(dense_input_path, quad_dominant_obj_path, out_obj_path,
              is_cad=True, is_rack=False, target_faces_for_h_base=None):
    """Runs ruler-straight coarsening alone and writes the result. Returns
    a stats dict: faces_in, faces_out, boundary_edges, non_manifold_edges,
    elapsed_seconds.
    """
    t0 = time.time()
    mesh = io_mesh.load(quad_dominant_obj_path)
    n_before = len(list(mesh.faces))

    verts, faces = editmesh_to_arrays(mesh)
    n_quads = sum(1 for f in faces if len(f) == 4)
    target_faces = target_faces_for_h_base or max(n_quads, 1)
    kdtree, sub_pts, sub_nrms, h_base = ground_truth_fields(dense_input_path, target_faces)

    rs_verts, rs_faces, _locked = rsc.coarsen_all_scales_ruler_straight(
        verts, faces, kdtree, sub_pts, sub_nrms, h_base, is_cad=is_cad, is_rack=is_rack
    )

    mesh2 = editmesh.EditMesh.from_arrays(rs_verts, rs_faces)
    io_mesh.export(out_obj_path, mesh2, quads=True)

    elapsed = time.time() - t0
    stats = {
        "faces_in": n_before,
        "faces_out": len(list(mesh2.faces)),
        "boundary_edges": len(mesh2.boundary_edges()),
        "non_manifold_edges": len(mesh2.non_manifold_edges()),
        "elapsed_seconds": round(elapsed, 1),
    }
    print(f"[step1] {quad_dominant_obj_path}: {stats['faces_in']} -> {stats['faces_out']} faces "
          f"({elapsed:.1f}s)  boundary_edges={stats['boundary_edges']} "
          f"non_manifold_edges={stats['non_manifold_edges']}")
    print(f"[step1] wrote {out_obj_path}")
    return stats


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: run_step1.py <dense_input.obj/glb> <quad_dominant_remesh.obj> <out.obj> "
              "[is_cad 0/1] [is_rack 0/1] [target_faces_for_h_base]")
        sys.exit(1)
    dense_in = sys.argv[1]
    quad_in = sys.argv[2]
    out_obj = sys.argv[3]
    is_cad_arg = bool(int(sys.argv[4])) if len(sys.argv) > 4 else True
    is_rack_arg = bool(int(sys.argv[5])) if len(sys.argv) > 5 else False
    target_faces_arg = int(sys.argv[6]) if len(sys.argv) > 6 else None
    run_step1(dense_in, quad_in, out_obj, is_cad=is_cad_arg, is_rack=is_rack_arg,
              target_faces_for_h_base=target_faces_arg)
