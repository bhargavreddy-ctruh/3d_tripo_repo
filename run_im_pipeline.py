#!/usr/bin/env python3
"""Run ONLY the Instant Meshes logic from 3d_tripo_repo (nondisk-planar-merge branch).

Pipeline:
1. decompose: split input mesh into connected components (islands)
2. sizing: compute continuous curvature field kappa and area-weighted target_faces_hint per component
3. remesh: run Instant Meshes (-D -S 1 -c 18.0 -r 4 -p 4 -d -b) on each component,
           with fragmentation check and fallback to quadric decimation/passthrough
4. optional 3b: volume-preserving strict coplanar merge + CAD reprojection per component
5. join: combine all remeshed components into a single multi-island OBJ
6. audit: report face count, quad %, tri %, and island metrics
"""

import argparse
import glob
import json
import os
import sys
import time

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_CORE_DIR = os.path.join(_THIS_DIR, "core")
for d in [_CORE_DIR, _THIS_DIR]:
    if d not in sys.path:
        sys.path.insert(0, d)

import config
import decompose
import sizing
import remesh
import join_components
import audit
import io_mesh
import run_coplanar_merge_step


def run_im_on_mesh(input_path, out_dir, do_coplanar_merge=True, angle_tol_deg=2.5):
    os.makedirs(out_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    t0 = time.time()
    report = {"input": input_path, "base_name": base_name, "timings": {}}

    print(f"\n=======================================================")
    print(f"Processing asset: {base_name}")
    print(f"Input: {input_path}")
    print(f"Output directory: {out_dir}")
    print(f"Coplanar merge: {'ENABLED (strict angle_tol=' + str(angle_tol_deg) + 'deg + reprojection)' if do_coplanar_merge else 'DISABLED (pure quad flow)'}")
    print(f"=======================================================")

    # 1. Decompose
    t = time.time()
    comps_dir = os.path.join(out_dir, f"{base_name}__components")
    print(f"[1/4] Decomposing into connected components...")
    manifest, manifest_path = decompose.decompose_to_components(input_path, comps_dir)
    report["timings"]["decompose"] = time.time() - t
    report["component_count"] = len(manifest)
    print(f"      Found {len(manifest)} components in {report['timings']['decompose']:.2f}s")

    # 2. Sizing
    t = time.time()
    print(f"[2/4] Estimating curvature-adaptive sizing per component...")
    sizing_results = sizing.estimate_manifest_sizing(manifest_path)
    report["timings"]["sizing"] = time.time() - t
    total_hint = sum(s.get("target_faces_hint", 0) for s in sizing_results)
    print(f"      Curvature sizing completed in {report['timings']['sizing']:.2f}s (total hint: {total_hint} faces)")

    # 3. Remesh (Instant Meshes with fallback)
    t = time.time()
    print(f"[3/4] Remeshing components via Instant Meshes (-D -c {config.CREASE_DEG} -r 4 -p 4)...")
    remesh_dir = os.path.join(out_dir, f"{base_name}__remeshed")
    remesh_results = remesh.remesh_manifest(manifest_path, sizing_results, remesh_dir)
    report["timings"]["remesh"] = time.time() - t
    backend_counts = {}
    remeshed_paths = []
    for r in remesh_results:
        backend_counts[r["backend"]] = backend_counts.get(r["backend"], 0) + 1
        if r["ok"] and r["out_obj"] and os.path.exists(r["out_obj"]):
            remeshed_paths.append(r["out_obj"])
        else:
            print(f"      Warning: Component {r['index']} failed remesh, using original geometry")
            remeshed_paths.append(r["in_obj"])

    report["remesh_backend_counts"] = backend_counts
    report["remesh_failures"] = [r["index"] for r in remesh_results if not r["ok"]]
    print(f"      Remeshing finished in {report['timings']['remesh']:.2f}s")
    print(f"      Backends used: {backend_counts}")

    # Optional 3b: Coplanar merge on every component separately
    paths_to_join = remeshed_paths
    if do_coplanar_merge:
        t = time.time()
        print(f"[3b/4] Running strict volume-preserving coplanar merge on {len(remeshed_paths)} components...")
        coplanar_dir = os.path.join(out_dir, f"{base_name}__coplanar")
        os.makedirs(coplanar_dir, exist_ok=True)
        merged_paths = []
        for idx, p in enumerate(remeshed_paths):
            base = os.path.splitext(os.path.basename(p))[0]
            out_p = os.path.join(coplanar_dir, f"{base}__coplanar.obj")
            pure_name = base.replace("__remeshed", "")
            orig_ref = os.path.join(comps_dir, f"{pure_name}.obj")
            if not os.path.exists(orig_ref):
                orig_ref = None
            try:
                run_coplanar_merge_step.process_single_component(
                    p, out_p, orig_ref_obj=orig_ref, angle_tol_deg=angle_tol_deg
                )
                merged_paths.append(out_p)
            except Exception as e:
                merged_paths.append(p)
        report["timings"]["coplanar_merge"] = time.time() - t
        print(f"      Coplanar merge completed in {report['timings']['coplanar_merge']:.2f}s")
        paths_to_join = merged_paths
        final_obj = os.path.join(out_dir, f"{base_name}__coplanar_final.obj")
    else:
        final_obj = os.path.join(out_dir, f"{base_name}__im_final.obj")

    # 4. Join components into final deliverable asset
    t = time.time()
    print(f"[4/4] Joining {len(paths_to_join)} components into final OBJ...")
    join_components.join(paths_to_join, final_obj)
    report["timings"]["join"] = time.time() - t
    report["final_obj"] = final_obj

    # 5. Audit
    t = time.time()
    audit_result = audit.audit_mesh(final_obj)
    report["timings"]["audit"] = time.time() - t
    report["audit"] = audit_result
    report["total_time"] = time.time() - t0

    report_path = os.path.join(out_dir, f"{base_name}__report.json")
    with open(report_path, "w") as fh:
        json.dump(report, fh, indent=2)
    report["report_path"] = report_path

    print(f"\nAsset {base_name} complete in {report['total_time']:.2f}s!")
    print(f"Audit Summary:")
    print(f"  Total Faces: {audit_result.get('faces', audit_result.get('total_faces', 0))}")
    print(f"  Quads:       {audit_result.get('quads', 0)} ({audit_result.get('quads_pct', 0):.1f}%)")
    print(f"  Triangles:   {audit_result.get('tris', 0)} ({audit_result.get('tris_pct', 0):.1f}%)")
    print(f"  N-gons:      {audit_result.get('ngons', 0)}")
    print(f"  Islands:     {audit_result.get('islands', 0)}")
    print(f"  Output OBJ:  {final_obj}")
    return report


def main():
    parser = argparse.ArgumentParser(description="Run 3d_tripo_repo Instant Meshes logic on 3D meshes")
    parser.add_argument("input", help="Path to input .glb, .gltf, or .obj file, or directory of assets")
    parser.add_argument("output_dir", help="Directory to store outputs")
    parser.add_argument("--no-coplanar", action="store_true", help="Skip per-component coplanar merge step (keep pure quad mesh)")
    parser.add_argument("--angle-tol", type=float, default=2.5, help="Dihedral angle tolerance in degrees for coplanar merge (default: 2.5 deg)")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    do_coplanar = not args.no_coplanar

    if os.path.isdir(args.input):
        exts = (".glb", ".gltf", ".obj")
        files = [
            os.path.join(args.input, f) for f in sorted(os.listdir(args.input))
            if os.path.splitext(f)[1].lower() in exts
        ]
        if not files:
            print(f"No 3D asset files found in {args.input}")
            sys.exit(1)
        print(f"Found {len(files)} assets in {args.input}")
        summary = []
        for f in files:
            try:
                rep = run_im_on_mesh(f, args.output_dir, do_coplanar_merge=do_coplanar, angle_tol_deg=args.angle_tol)
                summary.append(rep)
            except Exception as e:
                print(f"ERROR processing {f}: {e}")
        batch_report_path = os.path.join(args.output_dir, "batch_im_report.json")
        with open(batch_report_path, "w") as fh:
            json.dump(summary, fh, indent=2)
        print(f"\nAll assets completed! Batch report saved to {batch_report_path}")
    else:
        run_im_on_mesh(args.input, args.output_dir, do_coplanar_merge=do_coplanar, angle_tol_deg=args.angle_tol)


if __name__ == "__main__":
    main()
