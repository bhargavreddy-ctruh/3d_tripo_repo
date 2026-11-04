"""Winding-consistency fix — thin wrapper around EditMesh's own
`fix_winding_consistency()` (the same BFS flood-fill algorithm
`trimesh.repair.fix_winding` uses, adapted to arbitrary-arity faces so it
doesn't force triangulation and destroy quads/n-gons). Kept as its own
module/pipeline stage (called explicitly after caps.py, whose newly built
faces aren't guaranteed to match the surrounding mesh's winding) even
though `EditMesh.recalc_face_normals()` already calls the same fix
internally before every crease/dome-saddle test in protect.py.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def fix_winding_consistency(mesh):
    """Returns number of faces flipped; mutates mesh in place."""
    return mesh.fix_winding_consistency()


if __name__ == "__main__":
    import json
    import io_mesh

    args = sys.argv[1:]
    if len(args) < 2:
        print("Usage: python3 fix_winding.py <in.obj> <out.obj>")
        sys.exit(1)

    mesh = io_mesh.load(args[0])
    n_flipped = fix_winding_consistency(mesh)
    io_mesh.export(args[1], mesh, quads=True)

    print("FIX_WINDING_RESULT_JSON_START")
    print(json.dumps({"faces_flipped": n_flipped, "out_obj": args[1]}, indent=2))
    print("FIX_WINDING_RESULT_JSON_END")
