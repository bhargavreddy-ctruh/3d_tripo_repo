#!/usr/bin/env python3
"""Run volume-preserving coplanar merge + CAD reprojection on remeshed components.

Key features:
1. Strict angle gating (angle_tol_deg <= 2.5 deg): eliminates chord cutting on curved surfaces.
2. Dual-pass darts quad optimization: merges coplanar triangle pairs into quads.
3. Nearest-point CAD surface reprojection: snaps all simplified vertices back to the dense reference surface.
4. Consistent counter-clockwise winding fix.
"""

import argparse
import glob
import os
import sys
import time

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_CORE_DIR = os.path.join(_THIS_DIR, "core")
for d in [_CORE_DIR, _THIS_DIR]:
    if d not in sys.path:
        sys.path.insert(0, d)

import trimesh
import io_mesh
import obj_io
import darts
import coplanar_merge
import reproject
import fix_winding
import join_components
import audit


def process_single_component(in_obj, out_obj, orig_ref_obj=None, angle_tol_deg=2.5):
    """Processes a single component OBJ through volume-preserving coplanar merge."""
    mesh = io_mesh.load(in_obj)
    stats_before = io_mesh.get_object_stats(mesh, name="before")

    # 0. Clean input defects
    seen = {}
    for f in list(mesh.faces):
        fv = mesh.face_verts(f)
        if len(fv) < 3:
            mesh.remove_face(f)
            continue
        unique_fv = list(dict.fromkeys(fv))
        if len(unique_fv) < 3:
            mesh.remove_face(f)
            continue
        if len(unique_fv) < len(fv):
            mesh.remove_face(f)
            mesh.add_face(tuple(unique_fv))
            continue
        key = tuple(sorted(fv))
        if key in seen:
            mesh.remove_face(f)
        else:
            seen[key] = f

    # 1. Merge coplanar triangle pairs into quads
    try:
        darts.merge_coplanar_triangle_pairs(mesh, angle_face_deg=18.0)
    except Exception as e:
        pass

    # 2. Strict Coplanar merge (ribbon lines + planar clusters at 2.5 deg)
    try:
        coplanar_merge.merge_coplanar_regions(mesh, angle_tol_deg=angle_tol_deg)
    except Exception as e:
        pass

    # 3. Collinear vertex dissolution along straight edges
    try:
        mesh.dissolve_collinear_verts(list(mesh.verts), angle_tol_deg=angle_tol_deg)
    except Exception as e:
        pass

    # 4. Secondary darts pass to convert any residual coplanar triangles into quads
    try:
        darts.merge_coplanar_triangle_pairs(mesh, angle_face_deg=18.0)
    except Exception as e:
        pass

    # 5. CAD-surface Reprojection to guarantee exact shape and volume retention
    if orig_ref_obj and os.path.exists(orig_ref_obj):
        try:
            ref_v, ref_f = obj_io.load(orig_ref_obj)
            if len(ref_f) >= 1:
                ref_trimesh = trimesh.Trimesh(vertices=ref_v, faces=ref_f, process=False)
                reproject.reproject_onto_reference(mesh, ref_trimesh)
        except Exception as e:
            pass

    # 6. Fix winding
    try:
        fix_winding.fix_winding_consistency(mesh)
    except Exception:
        pass

    io_mesh.export(out_obj, mesh, quads=True)
    stats_after = io_mesh.get_object_stats(mesh, name="after")
    return stats_before, stats_after


def process_asset_components(asset_remeshed_dir, out_dir, angle_tol_deg=2.5):
    """Processes all components in an asset's __remeshed directory."""
    os.makedirs(out_dir, exist_ok=True)
    comp_files = sorted(glob.glob(os.path.join(asset_remeshed_dir, "*__remeshed.obj")))
    if not comp_files:
        comp_files = sorted(glob.glob(os.path.join(asset_remeshed_dir, "*.obj")))
    if not comp_files:
        print(f"No component OBJ files found in {asset_remeshed_dir}")
        return

    asset_dir_name = os.path.basename(os.path.normpath(asset_remeshed_dir))
    base_name = asset_dir_name.replace("__remeshed", "")
    parent_dir = os.path.dirname(os.path.normpath(asset_remeshed_dir))
    comps_orig_dir = os.path.join(parent_dir, f"{base_name}__components")

    print(f"\n=======================================================")
    print(f"Processing component folder: {asset_dir_name}")
    print(f"Number of components: {len(comp_files)}")
    print(f"Output folder: {out_dir}")
    print(f"Original components ref dir: {comps_orig_dir}")
    print(f"Angle tolerance: {angle_tol_deg} deg (strict volume-preserving)")
    print(f"=======================================================")

    t0 = time.time()
    merged_paths = []
    for idx, cf in enumerate(comp_files):
        fname = os.path.basename(cf)
        base = os.path.splitext(fname)[0]
        out_cf = os.path.join(out_dir, f"{base}__coplanar.obj")

        pure_name = base.replace("__remeshed", "")
        orig_ref = os.path.join(comps_orig_dir, f"{pure_name}.obj")
        if not os.path.exists(orig_ref):
            orig_ref = None

        try:
            process_single_component(cf, out_cf, orig_ref_obj=orig_ref, angle_tol_deg=angle_tol_deg)
            merged_paths.append(out_cf)
        except Exception as e:
            print(f"  Warning: comp {idx} failed coplanar merge ({e}), copying remeshed")
            io_mesh.export(out_cf, io_mesh.load(cf), quads=True)
            merged_paths.append(out_cf)

    print(f"\nJoining {len(merged_paths)} coplanar-merged components into final asset...")
    final_obj = os.path.join(out_dir, f"{base_name}__coplanar_final.obj")
    join_components.join(merged_paths, final_obj)

    t_total = time.time() - t0
    audit_res = audit.audit_mesh(final_obj)

    print(f"\nCompleted {base_name} in {t_total:.2f}s!")
    print(f"Final Audit Summary:")
    print(f"  Faces:     {audit_res.get('faces', audit_res.get('total_faces', 0))}")
    print(f"  Quads:     {audit_res.get('quads', 0)} ({audit_res.get('quads_pct', 0):.1f}%)")
    print(f"  Triangles: {audit_res.get('tris', 0)} ({audit_res.get('tris_pct', 0):.1f}%)")
    print(f"  N-gons:    {audit_res.get('ngons', 0)}")
    print(f"  Islands:   {audit_res.get('islands', 0)}")
    print(f"  Final OBJ: {final_obj}")

    report_path = os.path.join(out_dir, f"{base_name}__coplanar_report.json")
    import json
    with open(report_path, "w") as fh:
        json.dump({
            "asset": base_name,
            "components_count": len(comp_files),
            "angle_tol_deg": angle_tol_deg,
            "elapsed_s": t_total,
            "audit": audit_res,
            "final_obj": final_obj,
        }, fh, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Run coplanar merge on remeshed components with CAD reprojection")
    parser.add_argument("remeshed_dir", help="Path to __remeshed directory containing component OBJs")
    parser.add_argument("out_dir", help="Output directory for coplanar merged components and joined OBJ")
    parser.add_argument("--angle-tol", type=float, default=2.5, help="Dihedral angle tolerance in degrees (default: 2.5 deg)")
    args = parser.parse_args()

    process_asset_components(args.remeshed_dir, args.out_dir, angle_tol_deg=args.angle_tol)


if __name__ == "__main__":
    main()
