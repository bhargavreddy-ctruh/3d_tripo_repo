"""Pure-Python mesh I/O (OBJ/GLB/GLTF only — FBX is not supported by this
backend; use pre-converted OBJ/GLB inputs). Replaces io_blender.py: no
bpy/bmesh, no Blender process of any kind, in-process or subprocess.

Two load paths, matching how this pipeline actually uses files:
- `load_dense_input()`: the ORIGINAL asset passed to decompose.py. May be
  .glb/.gltf/.obj. decompose.py immediately splits this into loose
  components and re-exports them triangulated (quads=False), so
  triangulating on load here (trimesh's native behavior) changes nothing
  downstream — this matches the previous io_blender.py behavior exactly.
- `load()`: every OTHER .obj file in the pipeline (remesh output,
  dissolve/darts/coplanar_merge/caps/reproject output, per-component
  finals). These carry quads/n-gons that must survive the round trip, so
  this uses obj_io.py's arity-preserving reader, never trimesh.
"""

import os

import numpy as np
import trimesh

import obj_io
from editmesh import EditMesh


def load_dense_input(path):
    """Load the original dense input asset into an EditMesh. Triangulates
    on load (via trimesh) — correct here because decompose.py's own output
    is triangulated regardless (quads=False)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".obj":
        loaded = trimesh.load(path, force="mesh", process=True)
        if isinstance(loaded, trimesh.Scene):
            geoms = list(loaded.geometry.values())
            all_verts = []
            all_faces = []
            offset = 0
            for geom in geoms:
                if not isinstance(geom, trimesh.Trimesh) or len(geom.faces) == 0:
                    continue
                all_verts.extend(geom.vertices.tolist())
                all_faces.extend((f + offset).tolist() for f in geom.faces)
                offset += len(geom.vertices)
            return EditMesh.from_arrays(all_verts, all_faces)
        else:
            return EditMesh.from_arrays(loaded.vertices.tolist(), loaded.faces.tolist())
    if ext not in (".glb", ".gltf"):
        raise ValueError(
            f"Unsupported input extension: {ext} "
            f"(this pure-Python backend handles .obj/.glb/.gltf only, not FBX)"
        )
    loaded = trimesh.load(path, process=False, force="scene")
    geoms = list(loaded.geometry.values()) if isinstance(loaded, trimesh.Scene) else [loaded]
    all_verts = []
    all_faces = []
    offset = 0
    for geom in geoms:
        if not isinstance(geom, trimesh.Trimesh) or len(geom.faces) == 0:
            continue
        all_verts.extend(geom.vertices.tolist())
        all_faces.extend((f + offset).tolist() for f in geom.faces)
        offset += len(geom.vertices)
    return EditMesh.from_arrays(all_verts, all_faces)


def load(path):
    """Load a .obj file, preserving native face arity (quads/n-gons)."""
    ext = os.path.splitext(path)[1].lower()
    if ext != ".obj":
        raise ValueError(f"load() only supports .obj (got {ext}); use load_dense_input() for glb/gltf")
    vertices, faces = obj_io.load(path)
    return EditMesh.from_arrays(vertices, faces)


def export(path, mesh, quads=True):
    """Export an EditMesh to .obj. quads=True preserves native face arity
    (default, matches this pipeline's "quad-dominant export" convention);
    quads=False fan-triangulates every face first."""
    ext = os.path.splitext(path)[1].lower()
    if ext != ".obj":
        raise ValueError(f"export() only supports .obj (got {ext})")
    vertices, faces, _ = mesh.to_arrays()
    if not quads:
        faces = obj_io.triangulate_faces(faces)
    obj_io.write(path, vertices, faces)


def get_object_stats(mesh, name="mesh"):
    """Mirrors io_blender.get_object_stats, computed on an EditMesh."""
    n_quads = sum(1 for f in mesh.faces if len(mesh.face_verts(f)) == 4)
    n_tris = sum(1 for f in mesh.faces if len(mesh.face_verts(f)) == 3)
    n_ngons = sum(1 for f in mesh.faces if len(mesh.face_verts(f)) > 4)
    n_boundary = len(mesh.boundary_edges())
    n_nonmanifold = len(mesh.non_manifold_edges())
    n_faces = len(list(mesh.faces))
    return {
        "name": name,
        "verts": len(list(mesh.verts)),
        "faces": n_faces,
        "edges": len(list(mesh.edges)),
        "quads": n_quads,
        "tris": n_tris,
        "ngons": n_ngons,
        "quad_pct": round(100.0 * n_quads / max(1, n_faces), 2),
        "tri_pct": round(100.0 * n_tris / max(1, n_faces), 2),
        "boundary_edges": n_boundary,
        "nonmanifold_edges": n_nonmanifold,
        "islands": mesh.count_islands(),
    }
