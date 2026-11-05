"""Per-component finishing: dissolve -> darts -> coplanar_merge -> caps ->
reproject, all on ONE EditMesh in plain Python (no Blender, no scene
concept — a "fresh scene" is now just a fresh `io_mesh.load()` call).

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
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import io_mesh
import dissolve
import darts
import coplanar_merge
import caps
import reproject
import fix_winding


def finalize(remeshed_obj, original_dense_obj, out_obj, max_passes=20):
    """Each stage is independently fault-isolated: a failure in dissolve,
    darts, or caps rolls that one stage back (re-reads the mesh as it stood
    before that stage, a cheap re-`io_mesh.load()` from the same file) and
    continues with the rest, rather than discarding all prior work for the
    component. Safe degradation over total failure, per the Primary
    objective — a component that only gets dissolve+darts (caps failing) is
    still a correct, useful result.
    """
    mesh = io_mesh.load(remeshed_obj)

    stage_errors = {}

    # 1. Triangle-pair merge first (turns coplanar triangles into clean quads
    # so loop traversal can walk through them)
    darts_stats = None
    try:
        darts_stats = darts.merge_coplanar_triangle_pairs(mesh)
    except Exception as e:
        stage_errors["darts"] = str(e)

    # 2. Strict full-line pairwise quad simplification (preserves 100% quads and edge flow)
    dissolve_stats = None
    try:
        dissolve_stats = dissolve.simplify_component(mesh, max_passes=max_passes)
    except Exception as e:
        stage_errors["dissolve"] = str(e)
        mesh = io_mesh.load(remeshed_obj)

    # 3. Clean ribbon line simplification (seam-to-seam cross-line merges along beams)
    coplanar_merge_stats = None
    try:
        n_ribbon_lines = coplanar_merge.merge_ribbon_lines(mesh, max_passes=6)
        coplanar_merge_stats = {"ribbon_lines_merged": n_ribbon_lines}
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
    # lossless, not an approximation.
    collinear_cleanup_stats = None
    try:
        n_removed = mesh.dissolve_collinear_verts(list(mesh.verts))
        collinear_cleanup_stats = {"verts_removed": n_removed}
    except Exception as e:
        stage_errors["collinear_cleanup"] = str(e)

    caps_results = None
    try:
        caps_results = caps.cap_all_planar_boundaries(mesh)
    except Exception as e:
        stage_errors["caps"] = str(e)

    # caps.py's new faces (bevel ring + chord strips) are not guaranteed to
    # match the surrounding mesh's existing winding direction —
    # fix_winding.py's BFS-based repair (preserves quad/n-gon structure)
    # resolves the vast majority of it directly.
    winding_fix_stats = None
    try:
        n_flipped = fix_winding.fix_winding_consistency(mesh)
        winding_fix_stats = {"faces_flipped": n_flipped}
    except Exception as e:
        stage_errors["fix_winding"] = str(e)

    tmp_path = out_obj + ".pre_reproject.obj"
    io_mesh.export(tmp_path, mesh, quads=True)

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
    import json

    args = sys.argv[1:]
    if len(args) < 3:
        print("Usage: python3 finalize_component.py <remeshed.obj> <original_dense.obj> <out.obj>")
        sys.exit(1)
    try:
        result = finalize(args[0], args[1], args[2])
        result["ok"] = True
    except Exception as e:
        result = {"ok": False, "error": str(e), "out_obj": args[2]}
    print("FINALIZE_RESULT_JSON_START")
    print(json.dumps(result, indent=2))
    print("FINALIZE_RESULT_JSON_END")
