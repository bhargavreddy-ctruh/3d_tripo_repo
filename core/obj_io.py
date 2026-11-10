"""Minimal pure-Python Wavefront OBJ reader/writer that preserves native
face arity (quads/n-gons), unlike `trimesh.Trimesh` which is triangle-only
and silently triangulates on load. Every intermediate file in this
pipeline after the initial dense input is .obj, and several stages
(remesh output, dissolve/darts/coplanar_merge/caps output) depend on
quads surviving the round trip — this module is what makes that possible
without Blender.

Deliberately minimal: positions and faces only (vt/vn/mtl are read and
discarded), matching the previous io_blender.py exporter's own
export_uv=False/export_normals=False/export_materials=False settings.
"""

import os


def load(path):
    """Returns (vertices: list[tuple[float,float,float]],
    faces: list[tuple[int,...]]) with 0-based vertex indices, arbitrary
    face arity preserved as written in the file."""
    vertices = []
    faces = []
    with open(path, "r") as fh:
        for line in fh:
            line = line.strip()
            if not line or line[0] == "#":
                continue
            parts = line.split()
            tag = parts[0]
            if tag == "v":
                x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                vertices.append((x, y, z))
            elif tag == "f":
                idx = []
                n = len(vertices)
                for tok in parts[1:]:
                    # "v", "v/vt", "v/vt/vn", "v//vn" — take the vertex index only.
                    vi = int(tok.split("/")[0])
                    if vi < 0:
                        vi = n + vi + 1  # OBJ negative indices are relative to current count
                    idx.append(vi - 1)  # OBJ is 1-based
                if len(idx) >= 3:
                    faces.append(tuple(idx))
    return vertices, faces


def write(path, vertices, faces):
    """vertices: iterable of (x,y,z). faces: iterable of 0-based vertex
    index tuples (any arity >= 3)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w") as fh:
        for x, y, z in vertices:
            fh.write(f"v {float(x)!r} {float(y)!r} {float(z)!r}\n")
        for f in faces:
            fh.write("f " + " ".join(str(i + 1) for i in f) + "\n")


def triangulate_faces(faces):
    """Fan-triangulate every face with arity > 3. Used when a caller wants
    an all-triangle export (the equivalent of Blender's
    use_triangles=True / export_triangulated_mesh=True)."""
    tris = []
    for f in faces:
        if len(f) == 3:
            tris.append(f)
            continue
        for i in range(1, len(f) - 1):
            tris.append((f[0], f[i], f[i + 1]))
    return tris
