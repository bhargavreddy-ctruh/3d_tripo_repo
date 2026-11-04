"""Import several component OBJs and export them together as one asset
(kept as separate islands, NOT merged into one face-connected mesh — multi-
component output is correct per the Context section of the plan: real
Tripo exports are always multi-island). Pure Python, no Blender.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import io_mesh
from editmesh import EditMesh


def join(comp_paths, out_path):
    """Import comp_paths and export them together as one multi-island OBJ
    at out_path. Returns the number of components joined."""
    combined = EditMesh()
    for p in comp_paths:
        part = io_mesh.load(p)
        vertices, faces, _ = part.to_arrays()
        vid_of = [combined.add_vert(co) for co in vertices]
        for f in faces:
            combined.add_face([vid_of[i] for i in f])
    io_mesh.export(out_path, combined, quads=True)
    return len(comp_paths)


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 2:
        print("Usage: python3 join_components.py <comp1.obj> [comp2.obj ...] <out.obj>")
        sys.exit(1)
    *comp_paths, out_path = args
    n = join(comp_paths, out_path)
    print(f"Joined {n} components into {out_path}")
