"""CAD-surface reprojection: snap the simplified low-poly mesh back onto the
original dense input surface via nearest-surface-point projection — ports
Step 3.5 from tripo_smart_engine's ribbon_engine.py. Pure Python
(`trimesh.proximity.closest_point`), no Blender.

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

import numpy as np
import trimesh

import io_mesh
import obj_io


def reproject_onto_reference(mesh, reference_trimesh, offset=0.0):
    """Mutates mesh's vertex positions in place, snapping each to the
    nearest point on reference_trimesh's surface (the equivalent of
    Blender's SHRINKWRAP "NEAREST_SURFACEPOINT" mode)."""
    vids = sorted(mesh._vert_co.keys())
    points = np.array([mesh.vert_co(v) for v in vids])
    closest, _distance, triangle_id = trimesh.proximity.closest_point(reference_trimesh, points)
    if offset != 0.0:
        normals = reference_trimesh.face_normals[triangle_id]
        closest = closest + normals * offset
    for v, co in zip(vids, closest):
        mesh._vert_co[v] = co


def reproject_obj_files(low_poly_path, reference_path, out_path, offset=0.0):
    mesh = io_mesh.load(low_poly_path)
    ref_vertices, ref_faces = obj_io.load(reference_path)
    ref_faces = obj_io.triangulate_faces(ref_faces)
    reference_trimesh = trimesh.Trimesh(vertices=ref_vertices, faces=ref_faces, process=False)

    pre_coords = {v: mesh.vert_co(v).copy() for v in mesh.verts}
    reproject_onto_reference(mesh, reference_trimesh, offset=offset)
    diffs = [float(np.linalg.norm(mesh.vert_co(v) - pre_coords[v])) for v in mesh.verts]
    diag = reference_trimesh.bounding_box.extents
    diag = float(np.linalg.norm(diag))

    stats = {
        "n_verts": len(diffs),
        "max_shift": max(diffs) if diffs else 0.0,
        "mean_shift": sum(diffs) / len(diffs) if diffs else 0.0,
        "max_shift_frac_of_diag": (max(diffs) / diag) if diffs and diag else 0.0,
    }

    io_mesh.export(out_path, mesh, quads=True)
    stats["out_obj"] = out_path
    return stats


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 3:
        print("Usage: python3 reproject.py <low_poly.obj> <reference.obj> <out.obj>")
        sys.exit(1)
    stats = reproject_obj_files(args[0], args[1], args[2])
    print("REPROJECT_RESULT_JSON_START")
    print(json.dumps(stats, indent=2))
    print("REPROJECT_RESULT_JSON_END")
