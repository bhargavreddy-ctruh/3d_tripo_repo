"""bpy-based mesh I/O: import FBX/GLB/OBJ, export FBX/GLB/OBJ, per-object stats.

Must run inside Blender's Python: imported by the other core/ scripts, which
are themselves either imported in-process via the `bpy` pip module (the
normal pipeline.py path) or run standalone under the real Blender app
(`blender --background --python <script>.py -- <args>`). Never run directly.
Reuses the import/export flag conventions already proven in
tripo_smart_engine's decomposer.py (forward_axis='NEGATIVE_Z', up_axis='Y').
"""

import json
import os
import sys

import bpy
import bmesh


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block_collection in (bpy.data.meshes, bpy.data.materials, bpy.data.images):
        for block in list(block_collection):
            if block.users == 0:
                block_collection.remove(block)


def import_mesh(filepath):
    """Import filepath (.fbx/.glb/.gltf/.obj) into the current scene.

    Returns the list of imported MESH objects.
    """
    ext = os.path.splitext(filepath)[1].lower()
    before = set(bpy.data.objects)

    if ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=filepath)
    elif ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=filepath)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=filepath, forward_axis="NEGATIVE_Z", up_axis="Y")
    else:
        raise ValueError(f"Unsupported input extension: {ext}")

    new_objs = [o for o in bpy.data.objects if o not in before]
    mesh_objs = [o for o in new_objs if o.type == "MESH"]
    if not mesh_objs:
        # Fallback: some importers reuse/rename objects rather than creating
        # new ones in edge cases — scan the whole scene for mesh objects.
        mesh_objs = [o for o in bpy.data.objects if o.type == "MESH"]
    return mesh_objs


def export_mesh(filepath, objects=None, quads=True):
    """Export objects (default: all MESH objects in the scene) to filepath.

    quads=True avoids forced triangulation on FBX/OBJ exporters that support
    native quad/n-gon output — matches the project's "quad-dominant export
    as the only default" decision carried over from tripo-logic-approach-v2.
    """
    bpy.ops.object.select_all(action="DESELECT")
    targets = objects if objects is not None else [o for o in bpy.data.objects if o.type == "MESH"]
    for o in targets:
        o.select_set(True)
    if targets:
        bpy.context.view_layer.objects.active = targets[0]

    ext = os.path.splitext(filepath)[1].lower()
    os.makedirs(os.path.dirname(os.path.abspath(filepath)) or ".", exist_ok=True)

    if ext == ".fbx":
        bpy.ops.export_scene.fbx(
            filepath=filepath,
            use_selection=bool(objects),
            use_triangles=not quads,
        )
    elif ext == ".glb":
        bpy.ops.export_scene.gltf(
            filepath=filepath,
            export_format="GLB",
            use_selection=bool(objects),
        )
    elif ext == ".obj":
        bpy.ops.wm.obj_export(
            filepath=filepath,
            forward_axis="NEGATIVE_Z",
            up_axis="Y",
            export_selected_objects=bool(objects),
            export_uv=False,
            export_normals=False,
            export_materials=False,
            export_triangulated_mesh=not quads,
        )
    else:
        raise ValueError(f"Unsupported output extension: {ext}")


def _count_islands(bm):
    """Count connected components (loose parts) in a bmesh via a vertex flood fill."""
    visited = set()
    islands = 0
    verts = bm.verts
    for seed in verts:
        if seed.index in visited:
            continue
        islands += 1
        stack = [seed]
        visited.add(seed.index)
        while stack:
            v = stack.pop()
            for e in v.link_edges:
                other = e.other_vert(v)
                if other.index not in visited:
                    visited.add(other.index)
                    stack.append(other)
    return islands


def get_object_stats(obj):
    """Return a dict of mesh stats for a single MESH object (verts, faces,
    quad/tri/ngon counts, boundary/non-manifold edge counts, islands)."""
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    n_quads = sum(1 for f in bm.faces if len(f.verts) == 4)
    n_tris = sum(1 for f in bm.faces if len(f.verts) == 3)
    n_ngons = sum(1 for f in bm.faces if len(f.verts) > 4)
    n_boundary = sum(1 for e in bm.edges if e.is_boundary)
    n_nonmanifold = sum(1 for e in bm.edges if not e.is_manifold and not e.is_boundary)
    islands = _count_islands(bm)

    stats = {
        "name": obj.name,
        "verts": len(bm.verts),
        "faces": len(bm.faces),
        "edges": len(bm.edges),
        "quads": n_quads,
        "tris": n_tris,
        "ngons": n_ngons,
        "quad_pct": round(100.0 * n_quads / max(1, len(bm.faces)), 2),
        "tri_pct": round(100.0 * n_tris / max(1, len(bm.faces)), 2),
        "boundary_edges": n_boundary,
        "nonmanifold_edges": n_nonmanifold,
        "islands": islands,
    }
    bm.free()
    return stats


def get_scene_stats(objects=None):
    targets = objects if objects is not None else [o for o in bpy.data.objects if o.type == "MESH"]
    per_object = [get_object_stats(o) for o in targets]
    totals = {
        "object_count": len(per_object),
        "total_verts": sum(s["verts"] for s in per_object),
        "total_faces": sum(s["faces"] for s in per_object),
        "total_islands": sum(s["islands"] for s in per_object),
    }
    return {"objects": per_object, "totals": totals}


def bounding_box_diagonal(objects=None):
    """Mesh-scale reference used everywhere a tolerance must be derived from
    the asset's own size instead of a hardcoded absolute unit."""
    targets = objects if objects is not None else [o for o in bpy.data.objects if o.type == "MESH"]
    mins = [float("inf")] * 3
    maxs = [float("-inf")] * 3
    for o in targets:
        for corner in o.bound_box:
            world = o.matrix_world @ bpy_vector(corner)
            for i in range(3):
                mins[i] = min(mins[i], world[i])
                maxs[i] = max(maxs[i], world[i])
    diag = sum((maxs[i] - mins[i]) ** 2 for i in range(3)) ** 0.5
    return diag if diag > 0 else 1.0


def bpy_vector(corner):
    import mathutils
    return mathutils.Vector(corner)


if __name__ == "__main__":
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    if not args:
        print("Usage: blender --background --python io_blender.py -- <input_file> [output_file]")
        sys.exit(1)

    clear_scene()
    input_path = args[0]
    mesh_objs = import_mesh(input_path)
    stats = get_scene_stats(mesh_objs)
    stats["bbox_diagonal"] = bounding_box_diagonal(mesh_objs)
    print("IO_BLENDER_STATS_JSON_START")
    print(json.dumps(stats, indent=2))
    print("IO_BLENDER_STATS_JSON_END")

    if len(args) > 1:
        export_mesh(args[1], objects=mesh_objs)
        print(f"Exported to {args[1]}")
