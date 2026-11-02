"""Full orchestration: decompose -> per-component sizing/remesh/finalize ->
rejoin -> audit. Runs under system python3, shelling out to Blender for the
bpy-dependent stages (decompose, finalize, join, audit) and calling
sizing.py/remesh.py's own functions directly (they already run under system
python3 for curvature/trimesh access).
"""

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import sizing
import remesh


def _run_blender(script, args, timeout=600):
    cmd = [config.BLENDER_BIN, "--background", "--python", script, "--"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result


def _extract_json(stdout, start_marker, end_marker):
    if start_marker not in stdout:
        return None
    return json.loads(stdout.split(start_marker)[1].split(end_marker)[0].strip())


def run_pipeline(input_path, out_dir, max_dissolve_passes=20):
    os.makedirs(out_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    t0 = time.time()
    report = {"input": input_path, "base_name": base_name, "timings": {}}

    # Stage: decompose
    comps_dir = os.path.join(out_dir, f"{base_name}__components")
    t = time.time()
    res = _run_blender(os.path.join(os.path.dirname(__file__), "decompose.py"),
                        [input_path, comps_dir])
    decompose_result = _extract_json(res.stdout, "DECOMPOSE_RESULT_JSON_START", "DECOMPOSE_RESULT_JSON_END")
    if decompose_result is None:
        raise RuntimeError(f"decompose failed: {res.stdout[-2000:]}\n{res.stderr[-2000:]}")
    manifest_path = decompose_result["manifest"]
    report["timings"]["decompose"] = time.time() - t
    report["component_count"] = decompose_result["component_count"]

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

    # Stage: finalize each component (dissolve+darts+caps+reproject), one
    # Blender process per component.
    t = time.time()
    finalized_dir = os.path.join(out_dir, f"{base_name}__finalized")
    os.makedirs(finalized_dir, exist_ok=True)
    finalize_script = os.path.join(os.path.dirname(__file__), "finalize_component.py")
    with open(manifest_path) as fh:
        manifest = json.load(fh)
    comp_by_index = {c["index"]: c for c in manifest["components"]}

    finalized_paths = []
    finalize_results = []
    for r in remesh_results:
        idx = r["index"]
        if not r["ok"] or r["out_obj"] is None:
            continue
        original_dense = comp_by_index[idx]["path"]
        out_obj = os.path.join(finalized_dir, f"comp{idx:04d}__final.obj")
        fres = _run_blender(finalize_script, [r["out_obj"], original_dense, out_obj])
        fresult = _extract_json(fres.stdout, "FINALIZE_RESULT_JSON_START", "FINALIZE_RESULT_JSON_END")
        if fresult and fresult.get("ok") and os.path.exists(out_obj):
            finalized_paths.append(out_obj)
        else:
            # Finalize failed for this component (e.g. reprojection target
            # mismatch) — fall back to the pre-finalize remeshed/passthrough
            # geometry rather than dropping the component.
            finalized_paths.append(r["out_obj"])
        finalize_results.append({"index": idx, "ok": bool(fresult and fresult.get("ok")),
                                  "detail": fresult})
    report["timings"]["finalize"] = time.time() - t
    report["finalize_failures"] = [f["index"] for f in finalize_results if not f["ok"]]

    # Stage: rejoin all finalized components into one final asset.
    t = time.time()
    final_obj = os.path.join(out_dir, f"{base_name}__final.obj")
    join_script = os.path.join(os.path.dirname(__file__), "join_components.py")
    jres = _run_blender(join_script, finalized_paths + [final_obj])
    report["timings"]["join"] = time.time() - t

    # Stage: audit the final asset.
    t = time.time()
    audit_script = os.path.join(os.path.dirname(__file__), "audit.py")
    ares = _run_blender(audit_script, [final_obj])
    audit_result = _extract_json(ares.stdout, "AUDIT_JSON_START", "AUDIT_JSON_END")
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
