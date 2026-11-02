"""Uniform bmesh subdivision — used ONLY as the up-scaling half of
`pipeline.py`'s hard output-face-count band enforcement, when the
curvature-adaptive pipeline's natural (minimal, feature-preserving) result
already falls below the user-mandated floor. Runs under Blender (bpy).

This does not add any real detail the curvature field didn't already
call for — it's a last-resort density topper, not a quality improvement.
Kept honest in TECH_NOTES.md: a mesh that needed this is being forced
denser than this engine's own feature-preservation analysis says it needs
to be, specifically because the user requested a hard floor.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy
import bmesh

import io_blender


def subdivide_until(in_obj, out_obj, min_target_faces, max_passes=6):
    io_blender.clear_scene()
    objs = io_blender.import_mesh(in_obj)
    obj = objs[0]
    bm = bmesh.new()
    bm.from_mesh(obj.data)

    passes = 0
    while len(bm.faces) < min_target_faces and passes < max_passes:
        bm.edges.ensure_lookup_table()
        bmesh.ops.subdivide_edges(
            bm, edges=list(bm.edges), cuts=1,
            use_grid_fill=True, use_single_edge=False,
        )
        passes += 1

    bm.to_mesh(obj.data)
    obj.data.update()
    faces_after = len(bm.faces)
    bm.free()

    io_blender.export_mesh(out_obj, objects=[obj], quads=True)
    return {"passes": passes, "faces_after": faces_after, "out_obj": out_obj}


if __name__ == "__main__":
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    if len(args) < 3:
        print("Usage: blender --background --python subdivide_mesh.py -- <in.obj> <out.obj> <min_target_faces>")
        sys.exit(1)
    result = subdivide_until(args[0], args[1], int(args[2]))
    print("SUBDIVIDE_RESULT_JSON_START")
    print(json.dumps(result, indent=2))
    print("SUBDIVIDE_RESULT_JSON_END")
