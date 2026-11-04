"""Forensic topology audit — ported from tripo_smart_engine's audit.py
(already verified accurate by this project's own earlier research pass).
Same metrics, same formulas; reimplemented against this project's
`io_blender` helpers instead of a separately embedded Blender script, so it
shares the same import/bmesh conventions as the rest of vacuum_quad_engine.
Runs under Blender (bpy/bmesh): imported in-process by pipeline.py via the
`bpy` pip module, or standalone as `python3 audit.py <mesh_file>`.
"""

import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy
import bmesh
import numpy as np

import io_blender


def _count_islands_all(mesh_objs):
    total = 0
    for o in mesh_objs:
        bm = bmesh.new()
        bm.from_mesh(o.data)
        total += io_blender._count_islands(bm)
        bm.free()
    return total


def audit_mesh(filepath):
    io_blender.clear_scene()
    mesh_objs = io_blender.import_mesh(filepath)
    if not mesh_objs:
        return {"error": "No mesh objects found", "path": filepath}

    total_islands = _count_islands_all(mesh_objs)

    bpy.ops.object.select_all(action="DESELECT")
    for o in mesh_objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = mesh_objs[0]
    if len(mesh_objs) > 1:
        bpy.ops.object.join()
    obj = bpy.context.active_object

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.verts.ensure_lookup_table()

    total_f = len(bm.faces)
    total_v = len(bm.verts)
    total_e = len(bm.edges)

    quads = [f for f in bm.faces if len(f.verts) == 4]
    tris = [f for f in bm.faces if len(f.verts) == 3]
    ngons = [f for f in bm.faces if len(f.verts) > 4]

    boundary_edges = [e for e in bm.edges if e.is_boundary]
    non_manifold_edges = [e for e in bm.edges if len(e.link_faces) > 2]

    aspects = []
    parallelisms = []
    for q in quads:
        vs = [v.co for v in q.verts]
        e0 = vs[1] - vs[0]
        e1 = vs[2] - vs[1]
        e2 = vs[3] - vs[2]
        e3 = vs[0] - vs[3]
        l0, l1, l2, l3 = e0.length, e1.length, e2.length, e3.length
        u = 0.5 * (l0 + l2)
        v_l = 0.5 * (l1 + l3)
        ar = max(u, v_l) / max(min(u, v_l), 1e-6)
        aspects.append(ar)
        if l0 > 1e-6 and l2 > 1e-6:
            parallelisms.append(abs(e0.normalized().dot(e2.normalized())))

    valences = [len(v.link_edges) for v in bm.verts if not v.is_boundary]
    val_c = Counter(valences)
    val4_pct = (val_c[4] / max(len(valences), 1)) * 100.0

    tris_set = set(tris)
    tri_paired = 0
    for t in tris:
        if any(lf in tris_set for e in t.edges for lf in e.link_faces if lf != t):
            tri_paired += 1
    tri_paired_pct = (tri_paired / max(len(tris), 1)) * 100.0

    stats = {
        "path": filepath,
        "islands": total_islands,
        "verts": total_v,
        "edges": total_e,
        "faces": total_f,
        "quads": len(quads),
        "quads_pct": round(len(quads) / max(total_f, 1) * 100.0, 2),
        "tris": len(tris),
        "tris_pct": round(len(tris) / max(total_f, 1) * 100.0, 2),
        "ngons": len(ngons),
        "boundary_edges": len(boundary_edges),
        "non_manifold_edges": len(non_manifold_edges),
        "valence_4_pct": round(val4_pct, 2),
        "triangles_paired_pct": round(tri_paired_pct, 2),
        "aspect_median": round(float(np.median(aspects)), 2) if aspects else 1.0,
        "aspect_90th": round(float(np.percentile(aspects, 90)), 2) if aspects else 1.0,
        "aspect_max": round(float(np.max(aspects)), 2) if aspects else 1.0,
        "parallelism_median": round(float(np.median(parallelisms)), 4) if parallelisms else 1.0,
        "ar_under_2": round(sum(1 for a in aspects if a < 2.0) / max(len(aspects), 1) * 100.0, 1),
        "ar_2_to_5": round(sum(1 for a in aspects if 2.0 <= a < 5.0) / max(len(aspects), 1) * 100.0, 1),
        "ar_5_to_20": round(sum(1 for a in aspects if 5.0 <= a < 20.0) / max(len(aspects), 1) * 100.0, 1),
        "ar_over_20": round(sum(1 for a in aspects if a >= 20.0) / max(len(aspects), 1) * 100.0, 1),
    }
    bm.free()
    return stats


def print_audit_report(stats):
    name = os.path.basename(stats["path"])
    print("=" * 80)
    print(f"VACUUM_QUAD_ENGINE FORENSIC TOPOLOGY AUDIT: {name}")
    print("=" * 80)
    print(f"Topology:          {stats['verts']:,} Verts | {stats['faces']:,} Faces | {stats['edges']:,} Edges")
    print(f"Components:        {stats['islands']} Independent Islands")
    print(f"Composition:       Quads: {stats['quads']:,} ({stats['quads_pct']}%) | Tris: {stats['tris']:,} ({stats['tris_pct']}%) | N-gons: {stats['ngons']}")
    print(f"Manifold Status:   Boundary Edges: {stats['boundary_edges']:,} | Non-Manifold Edges: {stats['non_manifold_edges']}")
    print(f"Valence 4 (CC):    {stats['valence_4_pct']}% regular interior lattice")
    print(f"2-to-1 Darts:      {stats['triangles_paired_pct']}% of triangles paired into reduction darts")
    print(f"Aspect Ratios:     Median: {stats['aspect_median']}:1 | 90th%: {stats['aspect_90th']}:1 | Max: {stats['aspect_max']}:1")
    print(f"Histogram:         [1.0-2.0): {stats['ar_under_2']}% | [2.0-5.0): {stats['ar_2_to_5']}% | [5.0-20.0): {stats['ar_5_to_20']}% | [>=20.0): {stats['ar_over_20']}%")
    print("=" * 80)


if __name__ == "__main__":
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    if not args:
        print("Usage: python3 audit.py <mesh_file.(obj|fbx|glb)>")
        sys.exit(1)
    stats = audit_mesh(args[0])
    print_audit_report(stats)
    print("AUDIT_JSON_START")
    print(json.dumps(stats, indent=2))
    print("AUDIT_JSON_END")
