"""Catmull-Clark smooth subdivision — used ONLY as the up-scaling half of
`pipeline.py`'s hard output-face-count band enforcement, when the
curvature-adaptive pipeline's natural (minimal, feature-preserving) result
already falls below the user-mandated floor. Runs under Blender (bpy).

REAL BUG, found via a user-shared wireframe screenshot (2026-11-02): the
first version of this file used plain `bmesh.ops.subdivide_edges` (linear
cuts). That only chops each EXISTING coarse face into finer sub-faces
along perfectly straight lines -- it has no notion of the true curved
surface, so it just echoes the coarse mesh's own flat facets at a finer
grid, producing a visibly blocky/non-smooth result (confirmed directly:
the coarse mesh's large flat quads stayed flat and faceted, just chopped
into more of the same flat pieces). Catmull-Clark subdivision (a Blender
SUBSURF modifier, applied and baked) instead pulls the surface toward a
smooth limit surface at each level -- confirmed directly on a real asset
(koala) to produce a visibly rounded, smooth result at a comparable final
face count, instead of a blocky one. It also always outputs pure quads
regardless of the input mix (quads/tris/n-gons), which is a further quad%
improvement over the input.

Still not a quality improvement over the curvature-adaptive minimum this
pipeline naturally computes -- it's a last-resort density topper, used
only because the user requested a hard output floor. `pipeline.py`
reprojects the result back onto the original dense input afterward (see
`_enforce_output_face_band`) to correct for Catmull-Clark's natural
smoothing-induced shrinkage relative to the true surface.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy

import io_blender


def subdivide_until(in_obj, out_obj, min_target_faces, max_levels=4):
    io_blender.clear_scene()
    objs = io_blender.import_mesh(in_obj)
    obj = objs[0]

    depsgraph = bpy.context.evaluated_depsgraph_get()
    faces_after = len(obj.evaluated_get(depsgraph).data.polygons)
    levels = 0
    mod = None

    while faces_after < min_target_faces and levels < max_levels:
        levels += 1
        if mod is None:
            mod = obj.modifiers.new("vqe_subsurf", type="SUBSURF")
            mod.subdivision_type = 'CATMULL_CLARK'
        mod.levels = levels
        mod.render_levels = levels
        depsgraph = bpy.context.evaluated_depsgraph_get()
        faces_after = len(obj.evaluated_get(depsgraph).data.polygons)

    if mod is not None:
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=mod.name)
    faces_after = len(obj.data.polygons)

    io_blender.export_mesh(out_obj, objects=[obj], quads=True)
    return {"levels": levels, "faces_after": faces_after, "out_obj": out_obj}


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
