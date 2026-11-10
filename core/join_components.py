"""Import several component OBJs and export them together as one asset
(kept as separate objects/islands, NOT bpy-joined into one mesh — multi-
component output is correct per the Context section of the plan: real
Tripo exports are always multi-island). Runs under Blender: imported
in-process via the `bpy` pip module by pipeline.py, or standalone as
`python3 join_components.py <comp1.obj> [comp2.obj ...] <out.obj>`.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import io_blender


def join(comp_paths, out_path):
    """Import comp_paths and export them together as one multi-object asset
    at out_path. Returns the number of objects joined."""
    io_blender.clear_scene()
    all_objs = []
    for p in comp_paths:
        all_objs.extend(io_blender.import_mesh(p))
    io_blender.export_mesh(out_path, objects=all_objs, quads=True)
    return len(all_objs)


if __name__ == "__main__":
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    if len(args) < 2:
        print("Usage: python3 join_components.py <comp1.obj> [comp2.obj ...] <out.obj>")
        sys.exit(1)
    *comp_paths, out_path = args
    n = join(comp_paths, out_path)
    print(f"Joined {n} components into {out_path}")
