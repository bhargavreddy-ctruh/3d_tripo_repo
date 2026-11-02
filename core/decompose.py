"""Split a mesh into its connected components (islands) and export each as
its own OBJ — the direct fix for tripo_smart_engine's decomposer.py, which
joins every part into ONE object before remeshing (the root cause of its
global target_faces / global micro-feature-median bugs).

Runs under Blender (`blender --background --python decompose.py -- <in> <out_dir>`).
Each component keeps its own curvature field computed independently by
curvature.py downstream (run on that component's OBJ alone) — this is the
simplest correct way to make sizing/protection genuinely local without
needing to reconcile vertex ordering between bpy and trimesh/igl.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy
import bmesh

import io_blender


def decompose_to_components(input_path, out_dir):
    """Import input_path, split into loose connected components, export each
    as its own OBJ in out_dir. Returns a manifest list of dicts."""
    io_blender.clear_scene()
    mesh_objs = io_blender.import_mesh(input_path)

    # Join multi-object imports into one object first ONLY so we can run a
    # single loose-parts separation; this is NOT the same bug as
    # tripo_smart_engine's decomposer.py, because the join here is
    # immediately undone by the loose-parts split below — the end state is
    # always N separate component objects, never one joined mesh carried
    # forward into remeshing.
    bpy.ops.object.select_all(action="DESELECT")
    for o in mesh_objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = mesh_objs[0]
    if len(mesh_objs) > 1:
        bpy.ops.object.join()
    target = bpy.context.active_object

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.separate(type="LOOSE")
    bpy.ops.object.mode_set(mode="OBJECT")

    components = [o for o in bpy.data.objects if o.type == "MESH"]

    os.makedirs(out_dir, exist_ok=True)
    manifest = []
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    for i, obj in enumerate(components):
        stats = io_blender.get_object_stats(obj)
        comp_path = os.path.join(out_dir, f"{base_name}__comp{i:04d}.obj")
        io_blender.export_mesh(comp_path, objects=[obj], quads=False)
        diag = io_blender.bounding_box_diagonal([obj])
        manifest.append({
            "index": i,
            "path": comp_path,
            "bbox_diagonal": diag,
            **stats,
        })

    manifest_path = os.path.join(out_dir, f"{base_name}__manifest.json")
    with open(manifest_path, "w") as fh:
        json.dump({"source": input_path, "components": manifest}, fh, indent=2)

    return manifest, manifest_path


if __name__ == "__main__":
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    if len(args) < 2:
        print("Usage: blender --background --python decompose.py -- <input_file> <out_dir>")
        sys.exit(1)

    manifest, manifest_path = decompose_to_components(args[0], args[1])
    print("DECOMPOSE_RESULT_JSON_START")
    print(json.dumps({"component_count": len(manifest), "manifest": manifest_path}, indent=2))
    print("DECOMPOSE_RESULT_JSON_END")
