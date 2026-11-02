"""Coplanar triangle-pair / diamond-dart merging — ports
tripo_smart_engine's `apply_diamond_dart_adapters` (ribbon_engine.py) via
Blender's own `bmesh.ops.join_triangles`, which already does exactly this:
merge two adjacent triangles into a quad when they're coplanar enough and
their combined shape isn't too skewed. Runs under Blender (bpy/bmesh).
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy
import bmesh

import config
import io_blender


def merge_coplanar_triangle_pairs(bm, angle_face_deg=config.COPLANAR_DART_DEG,
                                   angle_shape_deg=90.0):
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    n_tris_before = sum(1 for f in bm.faces if len(f.verts) == 3)
    bmesh.ops.join_triangles(
        bm, faces=bm.faces,
        angle_face_threshold=math.radians(angle_face_deg),
        angle_shape_threshold=math.radians(angle_shape_deg),
    )
    bm.faces.ensure_lookup_table()
    n_tris_after = sum(1 for f in bm.faces if len(f.verts) == 3)
    return {"tris_before": n_tris_before, "tris_after": n_tris_after,
            "pairs_merged": (n_tris_before - n_tris_after) // 2}


def merge_obj_file(in_obj, out_obj, **kwargs):
    io_blender.clear_scene()
    objs = io_blender.import_mesh(in_obj)
    obj = objs[0]
    bm = bmesh.new()
    bm.from_mesh(obj.data)

    n_boundary_before = sum(1 for e in bm.edges if e.is_boundary)
    stats = merge_coplanar_triangle_pairs(bm, **kwargs)
    bm.edges.ensure_lookup_table()
    n_boundary_after = sum(1 for e in bm.edges if e.is_boundary)
    if n_boundary_after > n_boundary_before:
        raise RuntimeError(
            f"darts: boundary edges grew {n_boundary_before} -> {n_boundary_after}"
        )
    stats["boundary_before"] = n_boundary_before
    stats["boundary_after"] = n_boundary_after

    bm.to_mesh(obj.data)
    obj.data.update()
    bm.free()
    io_blender.export_mesh(out_obj, objects=[obj], quads=True)
    stats["out_obj"] = out_obj
    return stats


if __name__ == "__main__":
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    if len(args) < 2:
        print("Usage: blender --background --python darts.py -- <in.obj> <out.obj>")
        sys.exit(1)
    stats = merge_obj_file(args[0], args[1])
    print("DARTS_RESULT_JSON_START")
    print(json.dumps(stats, indent=2))
    print("DARTS_RESULT_JSON_END")
