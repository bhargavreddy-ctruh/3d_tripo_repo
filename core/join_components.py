"""Import several component OBJs and export them together as one asset
(kept as separate objects/islands, NOT bpy-joined into one mesh — multi-
component output is correct per the Context section of the plan: real
Tripo exports are always multi-island). Runs under Blender.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import io_blender


if __name__ == "__main__":
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    if len(args) < 2:
        print("Usage: blender --background --python join_components.py -- <comp1.obj> [comp2.obj ...] <out.obj>")
        sys.exit(1)
    *comp_paths, out_path = args
    io_blender.clear_scene()
    all_objs = []
    for p in comp_paths:
        all_objs.extend(io_blender.import_mesh(p))
    io_blender.export_mesh(out_path, objects=all_objs, quads=True)
    print(f"Joined {len(all_objs)} components into {out_path}")
