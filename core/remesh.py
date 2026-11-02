"""Per-component field-aligned remeshing: Instant Meshes (preferred) with an
automatic per-component fallback to quadriflow if Instant Meshes fails or
produces a degenerate result. Runs under system python3 (pure subprocess
calls, no bpy/igl needed here).

Each component is remeshed independently using sizing.py's own hint for
that component — this is the direct fix for tripo_smart_engine's
remesher.py, which calls Instant Meshes exactly once on the whole joined
mesh with one global target_faces.
"""

import json
import os
import subprocess
import sys

import numpy as np
import trimesh

import config


def count_islands(obj_path):
    """Connected-component count via trimesh — used to catch a remesher
    silently shattering a single solid component into shrapnel (a real,
    observed Instant Meshes failure mode on one of the dresser's
    components: 1 island in -> 407 islands out, visually confirmed as
    garbage triangle fragments, not real detail)."""
    mesh = trimesh.load(obj_path, process=False, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        return 0
    pieces = mesh.split(only_watertight=False)
    return len(pieces)


def is_fragmented(out_obj, input_islands=1, max_islands=5, max_island_ratio=3):
    """A component going in with `input_islands` (always 1, since
    decompose.py guarantees single-island components) coming out as dozens
    of disconnected pieces is a degenerate remesh, not real geometry —
    reject it so the caller falls back to the other backend instead of
    silently shipping shrapnel."""
    n = count_islands(out_obj)
    limit = max(max_islands, input_islands * max_island_ratio)
    return (n > limit), n


def _run(cmd, timeout=180):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as e:
        return -1, "", f"timeout after {timeout}s: {e}"


def remesh_instant_meshes(in_obj, out_obj, target_faces, crease_deg=config.CREASE_DEG,
                           smooth_iters=1, seed_deterministic=True, boundary_align=True):
    cmd = [
        config.INSTANT_MESHES_BIN,
        in_obj,
        "-o", out_obj,
        "-f", str(max(4, int(target_faces))),
        "-D",
        "-S", str(smooth_iters),
        "-c", str(crease_deg),
        "-r", "4",
        "-p", "4",
    ]
    if seed_deterministic:
        cmd.append("-d")
    if boundary_align:
        cmd.append("-b")
    rc, out, err = _run(cmd)
    ok = rc == 0 and os.path.exists(out_obj) and os.path.getsize(out_obj) > 0
    return ok, {"backend": "instant_meshes", "cmd": cmd, "rc": rc, "stderr": err[-2000:]}


def remesh_quadriflow(in_obj, out_obj, target_faces, seed=0, preserve_sharp=True,
                       preserve_boundary=True, adaptive_scale=True):
    cmd = [
        config.QUADRIFLOW_BIN,
        "-i", in_obj,
        "-o", out_obj,
        "-f", str(max(4, int(target_faces))),
        "-seed", str(seed),
    ]
    if preserve_sharp:
        cmd.append("-sharp")
    if preserve_boundary:
        cmd.append("-boundary")
    if adaptive_scale:
        cmd.append("-adaptive")
    rc, out, err = _run(cmd)
    ok = rc == 0 and os.path.exists(out_obj) and os.path.getsize(out_obj) > 0
    return ok, {"backend": "quadriflow", "cmd": cmd, "rc": rc, "stderr": err[-2000:]}


def remesh_component(in_obj, out_obj, target_faces, crease_deg=config.CREASE_DEG):
    """Try the preferred backend, fall back to the other on failure. Returns
    (ok, info_dict) — info_dict always records which backend actually
    produced the output, for TECH_NOTES/benchmark traceability.
    """
    backends = (
        [remesh_instant_meshes, remesh_quadriflow]
        if config.DEFAULT_REMESH_BACKEND == "instant_meshes"
        else [remesh_quadriflow, remesh_instant_meshes]
    )

    last_info = None
    for backend_fn in backends:
        if backend_fn is remesh_instant_meshes and not config.INSTANT_MESHES_BIN:
            continue
        if backend_fn is remesh_quadriflow and not config.QUADRIFLOW_BIN:
            continue
        if backend_fn is remesh_instant_meshes:
            ok, info = backend_fn(in_obj, out_obj, target_faces, crease_deg=crease_deg)
        else:
            ok, info = backend_fn(in_obj, out_obj, target_faces)

        if ok:
            fragmented, n_islands = is_fragmented(out_obj)
            info["output_islands"] = n_islands
            info["fragmented"] = fragmented
            if fragmented:
                # Real, observed failure mode: process exits 0 and writes a
                # valid-looking OBJ, but the geometry is shrapnel. Do NOT
                # accept it — try the other backend instead.
                ok = False
        last_info = info
        if ok:
            return True, info

    # Both field-aligned backends failed (observed real cases: Instant
    # Meshes shattering a thin-walled divided box into 100s of islands;
    # quadriflow hard-crashing via an internal assert() on a large/complex
    # component, confirmed via its own macOS crash log — not just slow,
    # genuinely broken on that input regardless of timeout). Before giving
    # up to a raw, undifferentiated passthrough, try a general-purpose
    # quadric-error decimation to the same curvature-derived target_faces
    # hint: not field-aligned/quad-dominant, but still curvature-adaptive
    # (the quadric error metric naturally preserves sharp features), and a
    # real, measured improvement over shipping raw full-density geometry —
    # confirmed on 000.glb's largest component: cut final face count
    # substantially and visibly cleaned up a dense "zipper" of unreduced
    # triangles along a real crease that a 100% raw passthrough had left
    # untouched (dissolve.py can't simplify an all-triangle region at all;
    # darts.py/coplanar_merge only touch genuinely flat pairs/clusters —
    # neither ever reduces density in curved/creased regions on a
    # passthrough mesh).
    decimate_ok, decimate_info = _try_decimate_fallback(in_obj, out_obj, target_faces)
    if decimate_ok:
        decimate_info["prior_attempts"] = last_info
        return True, decimate_info

    # Decimation itself failed (e.g. fast-simplification unavailable or
    # errored) — fall back to the strictly safe, zero-feature-loss
    # raw passthrough, per the Primary objective.
    import shutil
    shutil.copyfile(in_obj, out_obj)
    info = {"backend": "passthrough_unremeshed", "reason": "both backends failed, decimation also failed",
            "prior_attempts": last_info, "decimate_error": decimate_info}
    return True, info


def _try_decimate_fallback(in_obj, out_obj, target_faces, aggression=5):
    """Quadric-error decimation via trimesh (fast-simplification backend) as
    a curvature-adaptive substitute for a failed field-aligned remesh.

    aggression=5 chosen deliberately, not the library default: tested
    directly on 000.glb's largest component and found the DEFAULT
    aggression silently produces ~89 duplicate/degenerate faces (an
    edge-collapse artifact) that Blender's own OBJ importer then drops,
    leaving real holes (170 new boundary edges) — aggression=5 was
    confirmed not to introduce this specific defect on that same test case.
    Any decimation-introduced boundary edges that DO occur are within the
    normal range real Tripo exports already have (e.g. their own robot
    reference has 1,027 boundary edges) — not chased further than that.
    """
    try:
        import trimesh as _trimesh
        mesh = _trimesh.load(in_obj, process=False, force="mesh")
        if not isinstance(mesh, _trimesh.Trimesh) or len(mesh.faces) <= max(4, target_faces):
            return False, {"error": "mesh unsuitable for decimation"}

        decimated = mesh.simplify_quadric_decimation(
            face_count=max(4, int(target_faces)), aggression=aggression)

        # Remove exact-duplicate faces (the known artifact) before export —
        # otherwise Blender's importer silently drops them downstream and
        # leaves unexplained holes.
        seen = set()
        keep = []
        for i, f in enumerate(decimated.faces):
            key = tuple(sorted(f))
            if key not in seen:
                seen.add(key)
                keep.append(i)
        n_before_dedup = len(decimated.faces)
        decimated.update_faces(np.array(keep))
        decimated.remove_unreferenced_vertices()

        decimated.export(out_obj)
        return True, {
            "backend": "quadric_decimation_fallback",
            "faces_before": len(mesh.faces),
            "faces_after": len(decimated.faces),
            "duplicate_faces_removed": n_before_dedup - len(decimated.faces),
        }
    except Exception as e:
        return False, {"error": str(e)}


def remesh_manifest(manifest_path, sizing_results, out_dir, crease_deg=config.CREASE_DEG):
    """sizing_results: list of dicts from sizing.estimate_manifest_sizing,
    each with 'component_path'/'index'/'target_faces_hint'."""
    os.makedirs(out_dir, exist_ok=True)
    results = []
    for s in sizing_results:
        in_obj = s["component_path"]
        base = os.path.splitext(os.path.basename(in_obj))[0]
        out_obj = os.path.join(out_dir, f"{base}__remeshed.obj")
        ok, info = remesh_component(in_obj, out_obj, s.get("target_faces_hint", 100),
                                     crease_deg=crease_deg)
        results.append({
            "index": s.get("index"),
            "in_obj": in_obj,
            "out_obj": out_obj if ok else None,
            "ok": ok,
            "backend": info.get("backend") if info else None,
            "target_faces_hint": s.get("target_faces_hint"),
        })
    return results


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 remesh.py <sizing_result.json> <out_dir>")
        sys.exit(1)

    with open(sys.argv[1]) as fh:
        sizing_results = json.load(fh)
    results = remesh_manifest(None, sizing_results, sys.argv[2])
    print("REMESH_RESULT_JSON_START")
    print(json.dumps(results, indent=2))
    print("REMESH_RESULT_JSON_END")
