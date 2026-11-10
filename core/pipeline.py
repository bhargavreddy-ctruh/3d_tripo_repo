"""Full orchestration: decompose -> per-component sizing/remesh/finalize ->
rejoin -> audit.

Pure Python, no Blender anywhere (no bpy, no `blender` binary, in-process
or subprocess) — every stage is a plain function call sharing this one
process. decompose/finalize_component/join_components/audit (previously
bpy-dependent) now use EditMesh/io_mesh; sizing.py/remesh.py were already
Blender-free (trimesh/igl).

Only .obj/.glb/.gltf inputs are supported by this backend — FBX needs a
pure-Python or Assimp-based reader this project doesn't have yet (see
io_mesh.py's docstring); pre-convert .fbx assets to .glb/.obj first.

Each stage still gets a fresh mesh object via a plain `io_mesh.load()`/
`load_dense_input()` call, so state never leaks between stages or
components — same isolation discipline the old bpy `clear_scene()` call
provided, just without needing a "scene" concept to clear in the first
place.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import sizing
import remesh
import decompose
import finalize_component
import join_components
import audit


def run_pipeline(input_path, out_dir, max_dissolve_passes=20):
    os.makedirs(out_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    t0 = time.time()
    report = {"input": input_path, "base_name": base_name, "timings": {}}

    # Stage: decompose
    comps_dir = os.path.join(out_dir, f"{base_name}__components")
    t = time.time()
    manifest, manifest_path = decompose.decompose_to_components(input_path, comps_dir)
    report["timings"]["decompose"] = time.time() - t
    report["component_count"] = len(manifest)

    # Stage: sizing (direct call, same process)
    t = time.time()
    sizing_results = sizing.estimate_manifest_sizing(manifest_path)
    report["timings"]["sizing"] = time.time() - t

    # Stage: remesh (direct call, same process)
    t = time.time()
    remesh_dir = os.path.join(out_dir, f"{base_name}__remeshed")
    remesh_results = remesh.remesh_manifest(manifest_path, sizing_results, remesh_dir)
    report["timings"]["remesh"] = time.time() - t
    backend_counts = {}
    for r in remesh_results:
        backend_counts[r["backend"]] = backend_counts.get(r["backend"], 0) + 1
    report["remesh_backend_counts"] = backend_counts
    report["remesh_failures"] = [r["index"] for r in remesh_results if not r["ok"]]

    # Stage: finalize each component (dissolve+darts+caps+reproject), all in
    # this same process, one EditMesh per component.
    t = time.time()
    finalized_dir = os.path.join(out_dir, f"{base_name}__finalized")
    os.makedirs(finalized_dir, exist_ok=True)
    comp_by_index = {c["index"]: c for c in manifest}

    finalized_paths = []
    finalize_results = []
    for r in remesh_results:
        idx = r["index"]
        if not r["ok"] or r["out_obj"] is None:
            continue
        original_dense = comp_by_index[idx]["path"]
        out_obj = os.path.join(finalized_dir, f"comp{idx:04d}__final.obj")
        try:
            fresult = finalize_component.finalize(r["out_obj"], original_dense, out_obj)
            fresult["ok"] = True
        except Exception as e:
            fresult = {"ok": False, "error": str(e), "out_obj": out_obj}
        if fresult.get("ok") and os.path.exists(out_obj):
            finalized_paths.append(out_obj)
        else:
            # Finalize failed for this component (e.g. reprojection target
            # mismatch) — fall back to the pre-finalize remeshed/passthrough
            # geometry rather than dropping the component.
            finalized_paths.append(r["out_obj"])
        finalize_results.append({"index": idx, "ok": bool(fresult.get("ok")),
                                  "detail": fresult})
    report["timings"]["finalize"] = time.time() - t
    report["finalize_failures"] = [f["index"] for f in finalize_results if not f["ok"]]

    # Stage: rejoin all finalized components into one final asset.
    t = time.time()
    final_obj = os.path.join(out_dir, f"{base_name}__final.obj")
    join_components.join(finalized_paths, final_obj)
    report["timings"]["join"] = time.time() - t

    # Stage: audit the final asset.
    t = time.time()
    audit_result = audit.audit_mesh(final_obj)
    report["timings"]["audit"] = time.time() - t
    report["audit"] = audit_result
    report["final_obj"] = final_obj
    report["total_time"] = time.time() - t0

    report_path = os.path.join(out_dir, f"{base_name}__report.json")
    with open(report_path, "w") as fh:
        json.dump(report, fh, indent=2)
    report["report_path"] = report_path

    return report


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 pipeline.py <input_file> <out_dir>")
        sys.exit(1)
    report = run_pipeline(sys.argv[1], sys.argv[2])
    print("PIPELINE_REPORT_JSON_START")
    print(json.dumps(report, indent=2))
    print("PIPELINE_REPORT_JSON_END")
