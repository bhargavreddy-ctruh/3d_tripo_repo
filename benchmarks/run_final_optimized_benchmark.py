import os
import sys
import time
import json
import numpy as np

sys.path.insert(0, os.path.abspath('isolated_pipeline'))
import io_mesh
import finalize_component
import audit
import render_honest_wireframe

ASSETS = [
    {
        "name": "woodenrack_854k",
        "type": "Planar Furniture (6 Knobs + Drawers)",
        "remeshed": ["outputs/woodenrack_test/woodenrack_854k__remeshed/woodenrack_854k__comp0000__remeshed.obj"],
        "dense": ["outputs/woodenrack_test/woodenrack_854k__components/woodenrack_854k__comp0000.obj"],
        "out_dir": "outputs/woodenrack_test/woodenrack_854k__finalized",
        "final_obj": "outputs/woodenrack_test/woodenrack_854k__gen_final.obj",
        "render_view": {"elev": 15, "azim": 30}
    },
    {
        "name": "002",
        "type": "Mechanical Assembly (5 Components)",
        "remeshed": [f"outputs/002_clean_verified/002__remeshed/002__comp{i:04d}__remeshed.obj" for i in range(5)],
        "dense": [f"outputs/002_clean_verified/002__components/002__comp{i:04d}.obj" for i in range(5)],
        "out_dir": "outputs/002_clean_verified/002__finalized",
        "final_obj": "outputs/002_clean_verified/002__gen_final.obj",
        "render_view": {"elev": 20, "azim": 45}
    },
    {
        "name": "sofa_860k",
        "type": "Mixed Planar Frame + Organic Cushions",
        "remeshed": [f"outputs/sofa_clean_verified/sofa_860k__remeshed/sofa_860k__comp{i:04d}__remeshed.obj" for i in range(2)],
        "dense": [f"outputs/sofa_clean_verified/sofa_860k__components/sofa_860k__comp{i:04d}.obj" for i in range(2)],
        "out_dir": "outputs/sofa_clean_verified/sofa_860k__finalized",
        "final_obj": "outputs/sofa_clean_verified/sofa_860k__gen_final.obj",
        "render_view": {"elev": 25, "azim": 45}
    }
]

ARTIFACTS_DIR = "/Users/bhargavreddy/.gemini/antigravity/brain/26b65ec2-027d-4c84-ae02-037d7277a076"
os.makedirs(ARTIFACTS_DIR, exist_ok=True)

summary_results = []

for asset in ASSETS:
    print(f"\n=======================================================")
    print(f"BENCHMARKING ASSET: {asset['name']} ({asset['type']})")
    print(f"=======================================================")
    t0 = time.time()
    os.makedirs(asset["out_dir"], exist_ok=True)

    component_objs = []
    for idx, (rem_p, den_p) in enumerate(zip(asset["remeshed"], asset["dense"])):
        comp_out = os.path.join(asset["out_dir"], f"comp{idx:04d}__gen_final.obj")
        print(f"  Finalizing comp{idx:04d} ({rem_p})...")
        res = finalize_component.finalize(rem_p, den_p, comp_out, max_passes=20)
        component_objs.append(comp_out)

    # Join components into unified final mesh
    total_verts = []
    total_faces = []
    v_offset = 0
    for comp_p in component_objs:
        m = io_mesh.load(comp_p)
        for v in m.verts:
            total_verts.append(m.vert_co(v))
        for f in m.faces:
            fv = [v + v_offset for v in m.face_verts(f)]
            total_faces.append(fv)
        v_offset += len(m.verts)

    import editmesh
    unified_mesh = editmesh.EditMesh()
    for co in total_verts:
        unified_mesh.add_vert(co)
    for fv in total_faces:
        unified_mesh.add_face(fv)

    io_mesh.export(asset["final_obj"], unified_mesh, quads=True)
    dt = time.time() - t0

    # Audit invariants
    report = audit.audit_mesh(asset["final_obj"])
    total_f = report["faces"]
    quads = report["quads"]
    tris = report["tris"]
    ngons = report["ngons"]
    q_pct = round(report["quads_pct"], 2)
    t_pct = round(report["tris_pct"], 2)
    nm_edges = report["non_manifold_edges"]
    b_cracks = report["boundary_edges"]

    print(f"Asset {asset['name']} Complete in {dt:.1f}s:")
    print(f"  Faces: {total_f} (Quads: {quads} [{q_pct}%], Tris: {tris} [{t_pct}%], N-Gons: {ngons})")
    print(f"  Non-Manifold Edges: {nm_edges}, Boundary Edges: {b_cracks}")

    # Render honest wireframe view
    render_out = os.path.join(ARTIFACTS_DIR, f"{asset['name']}__final_optimized_render.png")
    try:
        render_honest_wireframe.render(
            asset["final_obj"],
            render_out,
            title=f"{asset['name']} Final ({total_f} faces, {q_pct}% quads)",
            elev=asset["render_view"]["elev"],
            azim=asset["render_view"]["azim"]
        )
        print(f"  Rendered wireframe -> {render_out}")
    except Exception as e:
        print(f"  Wireframe render failed: {e}")

    summary_results.append({
        "asset": asset["name"],
        "type": asset["type"],
        "total_faces": total_f,
        "quads": quads,
        "quad_pct": q_pct,
        "tris": tris,
        "tri_pct": t_pct,
        "ngons": ngons,
        "non_manifold_edges": nm_edges,
        "boundary_edges": b_cracks,
        "runtime_s": round(dt, 1),
        "render_path": render_out
    })

summary_path = os.path.join(ARTIFACTS_DIR, "final_optimized_benchmark_summary.json")
with open(summary_path, "w") as f:
    json.dump(summary_results, f, indent=2)

print(f"\nAll Benchmarks Completed! Summary written to {summary_path}")

