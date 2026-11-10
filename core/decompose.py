"""Split a mesh into its connected components (islands) and export each as
its own OBJ — the direct fix for tripo_smart_engine's decomposer.py, which
joins every part into ONE object before remeshing (the root cause of its
global target_faces / global micro-feature-median bugs).

Pure Python (trimesh connected-components, no Blender of any kind). Each
component keeps its own curvature field computed independently by
curvature.py downstream (run on that component's OBJ alone) — this is the
simplest correct way to make sizing/protection genuinely local without
needing to reconcile vertex ordering between different libraries.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import io_mesh


def decompose_to_components(input_path, out_dir):
    """Import input_path, split into loose connected components, export each
    as its own triangulated OBJ in out_dir. Returns (manifest, manifest_path)."""
    mesh = io_mesh.load_dense_input(input_path)
    vertices, faces, _ = mesh.to_arrays()

    # Connected-component labeling over the face-adjacency graph (shared
    # vertex), the exact equivalent of Blender's "separate by loose parts".
    n = len(vertices)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for f in faces:
        for i in range(1, len(f)):
            union(f[0], f[i])

    groups = {}
    for fi, f in enumerate(faces):
        root = find(f[0])
        groups.setdefault(root, []).append(fi)

    os.makedirs(out_dir, exist_ok=True)
    manifest = []
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    for i, (_root, face_indices) in enumerate(sorted(groups.items())):
        used_verts = sorted({v for fi in face_indices for v in faces[fi]})
        remap = {v: j for j, v in enumerate(used_verts)}
        comp_vertices = [vertices[v] for v in used_verts]
        comp_faces = [tuple(remap[v] for v in faces[fi]) for fi in face_indices]
        comp_mesh = io_mesh.EditMesh.from_arrays(comp_vertices, comp_faces)

        comp_path = os.path.join(out_dir, f"{base_name}__comp{i:04d}.obj")
        io_mesh.export(comp_path, comp_mesh, quads=False)
        diag = comp_mesh.bounding_box_diagonal()
        stats = io_mesh.get_object_stats(comp_mesh, name=f"comp{i:04d}")
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
    args = sys.argv[1:]
    if len(args) < 2:
        print("Usage: python3 decompose.py <input_file> <out_dir>")
        sys.exit(1)

    manifest, manifest_path = decompose_to_components(args[0], args[1])
    print("DECOMPOSE_RESULT_JSON_START")
    print(json.dumps({"component_count": len(manifest), "manifest": manifest_path}, indent=2))
    print("DECOMPOSE_RESULT_JSON_END")
