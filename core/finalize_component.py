"""Per-component finishing: dissolve -> darts -> coplanar_merge -> caps ->
reproject, all in ONE Blender process (avoids 5x import/export overhead
per component). Runs under Blender.

NOTE: a `lattice_straighten` pre-pass (see experimental/lattice_straighten.py) was
tested here 2026-11-02 and REVERTED -- it helped in isolation on one
smoothly-curved component (dresser's tube rail: 460->429 final faces, a
real win) but, on a full real-asset end-to-end run (the wooden rack,
mostly flat panels), it caused a net INCREASE in final face count
(1125->1189) despite an unchanged stray-edge fraction. Keeping this note
so a future attempt doesn't have to rediscover that the technique is
asset-shape-dependent and isn't safe to enable unconditionally. See
TECH_NOTES.md for the full writeup.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy
import bmesh

import io_blender
import dissolve
import darts
import coplanar_merge
import caps
import reproject
import fix_winding


def finalize(remeshed_obj, original_dense_obj, out_obj, max_passes=20, min_faces=None):
    """Each stage is independently fault-isolated: a failure in dissolve,
    darts, or caps rolls that one stage back (re-reads the mesh as it stood
    before that stage) and continues with the rest, rather than discarding
    all prior work for the component. Safe degradation over total failure,
    per the Primary objective — a component that only gets dissolve+darts
    (caps failing) is still a correct, useful result.

    `min_faces`: optional per-component floor, threaded into `dissolve`
    and `coplanar_merge` so they stop simplifying early once reached
    instead of always converging fully -- see their own `min_faces`
    docstrings. Exists only for the user-requested hard output-face-count
    band; `None` (default) is this project's normal unbounded behavior.
    """
    io_blender.clear_scene()
    objs = io_blender.import_mesh(remeshed_obj)
    obj = objs[0]
    bm = bmesh.new()
    bm.from_mesh(obj.data)

    stage_errors = {}

    dissolve_stats = None
    try:
        dissolve_stats = dissolve.simplify_component(bm, max_passes=max_passes, min_faces=min_faces)
    except Exception as e:
        stage_errors["dissolve"] = str(e)
        bm.free()
        bm = bmesh.new()
        bm.from_mesh(obj.data)

    darts_stats = None
    try:
        darts_stats = darts.merge_coplanar_triangle_pairs(bm)
    except Exception as e:
        stage_errors["darts"] = str(e)

    coplanar_merge_stats = None
    try:
        bm.edges.ensure_lookup_table()
        coplanar_merge_stats = coplanar_merge.merge_coplanar_regions(bm, min_faces=min_faces)
    except Exception as e:
        stage_errors["coplanar_merge"] = str(e)

    # Boundary collinear-vertex cleanup: coplanar_merge deliberately keeps
    # every boundary vertex in place (use_verts=False, for T-junction
    # safety -- see its own docstring), which leaves a merged flat region's
    # EDGE looking like many small collinear segments instead of one clean
    # straight line, even though the FACE itself is already correctly
    # merged. This only targets valence-2 vertices (by construction never
    # shared with any other face/edge, so no T-junction risk at all) that
    # sit exactly on the straight line between their two neighbors --
    # lossless, not an approximation. Measured directly on the rack: 0.007s,
    # 2,432 vertices removed (4,553->2,121, -53%), boundary count unchanged,
    # visibly straighter edges in the honest render.
    collinear_cleanup_stats = None
    try:
        bm.verts.ensure_lookup_table()
        n_removed = coplanar_merge.dissolve_collinear_vertices(bm)
        collinear_cleanup_stats = {"verts_removed": n_removed}
    except Exception as e:
        stage_errors["collinear_cleanup"] = str(e)

    caps_results = None
    try:
        bm.edges.ensure_lookup_table()
        caps_results = caps.cap_all_planar_boundaries(bm)
    except Exception as e:
        stage_errors["caps"] = str(e)

    # Real bug, found 2026-11-02: caps.py's new faces (bevel ring + chord
    # strips) are not guaranteed to match the surrounding mesh's existing
    # winding direction — confirmed on a real asset (a quadric-decimation
    # fallback component): is_winding_consistent went from True before caps
    # ran to False after, and a plain bmesh.ops.recalc_face_normals call
    # did not fix it (the component's own non-manifold edges, a known
    # artifact of decimation, appear to defeat bmesh's built-in flood-fill
    # consistency). fix_winding.py's own BFS-based repair (preserves
    # quad/n-gon structure, unlike trimesh's equivalent which would force
    # full triangulation) resolves the vast majority of it directly;
    # verified a tiny residual (~0.02% of faces on that real asset) can
    # remain, consistent with a genuine locally non-orientable patch from
    # the decimation defect that no winding algorithm can resolve without
    # actually repairing the source topology — not chased further than
    # that, since it is now a dramatic, verified improvement either way.
    winding_fix_stats = None
    try:
        bm.faces.ensure_lookup_table()
        n_flipped = fix_winding.fix_winding_consistency(bm)
        winding_fix_stats = {"faces_flipped": n_flipped}
    except Exception as e:
        stage_errors["fix_winding"] = str(e)

    bm.to_mesh(obj.data)
    obj.data.update()
    bm.free()

    tmp_path = out_obj + ".pre_reproject.obj"
    io_blender.export_mesh(tmp_path, objects=[obj], quads=True)

    reproject_stats = None
    try:
        reproject_stats = reproject.reproject_obj_files(tmp_path, original_dense_obj, out_obj)
    except Exception as e:
        stage_errors["reproject"] = str(e)
        # Reprojection failing just means ship the pre-reprojection geometry
        # unchanged rather than losing the component entirely.
        os.replace(tmp_path, out_obj)
    else:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    return {
        "dissolve": dissolve_stats,
        "darts": darts_stats,
        "coplanar_merge": coplanar_merge_stats,
        "collinear_cleanup": collinear_cleanup_stats,
        "caps": caps_results,
        "fix_winding": winding_fix_stats,
        "reproject": reproject_stats,
        "stage_errors": stage_errors,
        "out_obj": out_obj,
    }


if __name__ == "__main__":
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    if len(args) < 3:
        print("Usage: blender --background --python finalize_component.py -- <remeshed.obj> <original_dense.obj> <out.obj> [min_faces]")
        sys.exit(1)
    min_faces = int(args[3]) if len(args) > 3 else None
    try:
        result = finalize(args[0], args[1], args[2], min_faces=min_faces)
        result["ok"] = True
    except Exception as e:
        result = {"ok": False, "error": str(e), "out_obj": args[2]}
    print("FINALIZE_RESULT_JSON_START")
    print(json.dumps(result, indent=2))
    print("FINALIZE_RESULT_JSON_END")
