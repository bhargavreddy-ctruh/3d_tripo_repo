"""CAD-surface reprojection: snap the simplified low-poly mesh back onto the
original dense input surface via Blender's SHRINKWRAP modifier — ports Step
3.5 from tripo_smart_engine's ribbon_engine.py. Runs under Blender (bpy).

This exists because every prior stage (remesh/dissolve/darts) only ever
removes or merges edges — it never actively corrects small positional drift
a field-aligned remesher can introduce relative to the true input surface.
Reprojection is the final guarantee that simplifying face count never pulls
the result away from the original shape.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy
import bmesh

import io_blender


def reproject_onto_reference(low_poly_obj, reference_obj, offset=0.0):
    """Apply a SHRINKWRAP modifier on low_poly_obj targeting reference_obj,
    then apply it (bake the deformation into the mesh)."""
    mod = low_poly_obj.modifiers.new(name="vqe_reproject", type="SHRINKWRAP")
    mod.target = reference_obj
    mod.offset = offset
    mod.wrap_method = "NEAREST_SURFACEPOINT"

    bpy.context.view_layer.objects.active = low_poly_obj
    bpy.ops.object.modifier_apply(modifier=mod.name)


def reproject_obj_files(low_poly_path, reference_path, out_path, offset=0.0):
    io_blender.clear_scene()
    low_objs = io_blender.import_mesh(low_poly_path)
    low_obj = low_objs[0]

    ref_objs = io_blender.import_mesh(reference_path)
    ref_obj = ref_objs[0]

    # Record pre-reprojection vertex positions for a deviation check.
    pre_coords = [v.co.copy() for v in low_obj.data.vertices]

    reproject_onto_reference(low_obj, ref_obj, offset=offset)

    post_coords = [v.co for v in low_obj.data.vertices]
    diffs = [(a - b).length for a, b in zip(pre_coords, post_coords)]
    diag = io_blender.bounding_box_diagonal([ref_obj])

    stats = {
        "n_verts": len(diffs),
        "max_shift": max(diffs) if diffs else 0.0,
        "mean_shift": sum(diffs) / len(diffs) if diffs else 0.0,
        "max_shift_frac_of_diag": (max(diffs) / diag) if diffs and diag else 0.0,
    }

    bpy.data.objects.remove(ref_obj, do_unlink=True)
    io_blender.export_mesh(out_path, objects=[low_obj], quads=True)
    stats["out_obj"] = out_path
    return stats


if __name__ == "__main__":
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    if len(args) < 3:
        print("Usage: blender --background --python reproject.py -- <low_poly.obj> <reference.obj> <out.obj>")
        sys.exit(1)
    stats = reproject_obj_files(args[0], args[1], args[2])
    print("REPROJECT_RESULT_JSON_START")
    print(json.dumps(stats, indent=2))
    print("REPROJECT_RESULT_JSON_END")
